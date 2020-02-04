#!/usr/bin/env python3

import torch
import torch.nn as nn
from torchvision.models import vgg16, resnet18
import torchvision.transforms as transforms
from itertools import repeat
import unittest
from captum.attr._core.layer_wise_relevance_propagation import LRP, LRP_0
from captum.attr._utils.lrp_rules import (
    EpsilonRhoRule,
    EpsilonRule,
    BasicRule,
    GammaRule,
    Alpha1_Beta0_Rule,
    zB_Rule,
    suggested_rules,
    Z_Rule
)
from captum.attr import visualization as viz

from .helpers.basic_models import BasicModel_ConvNet_One_Conv
from .helpers.utils import BaseTest, assertTensorAlmostEqual

import math
from PIL import Image
import numpy as np
import os
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap


def _get_basic_config():
    input = torch.arange(16).view(1, 1, 4, 4).float()
    grads = torch.tensor([-0.0, -0.0, -0.0, 1.0, 1.0, -0.0])
    expected_activations = torch.tensor([[54.1300, 54.1880, 54.2934, 53.9288]])
    return BasicModel_ConvNet_One_Conv(), input, grads, expected_activations, None


def _get_rule_config():
    relevance = torch.tensor([[[-0.0, 3.0]]])
    layer = nn.modules.Conv1d(1, 1, 2, bias=False)
    nn.init.constant_(layer.weight.data, 2)
    activations = torch.tensor([[[1.0, 5.0, 7.0]]])
    input = torch.tensor([2, 0, -2])
    return relevance, layer, activations, input


def _get_vgg_config():
    model = vgg16(pretrained=True)
    model.eval()
    image = _convert_image("images\\castle.jpg")
    image2 = _convert_image("images\\dackel.jpg")
    return model, image, image2


class Test(BaseTest):
    def test_lrp_test_hook_activations(self):
        self._activations_base_assert(
            *_get_basic_config(), implementation="forward_hook"
        )

    def test_lrp_creator(self):
        self._creator_error_assert(*_get_basic_config(), error="ruleType")

    def test_lrp_creator_activation(self):
        self._creator_error_assert(*_get_basic_config(), error="activationType")

    def test_lrp_basic_attributions(self):
        self._basic_attributions(*_get_basic_config())

    def test_lrp_simple_attributions(self):
        self._simple_attributions()

    def test_lrp_vgg(self):
        self._attributions_assert_vgg(*_get_vgg_config())

    def test_basic_rule(self):
        self._rule_assert(*_get_rule_config(), rule="BasicPropagate")

    def test_basic_rule_function(self):
        self._rule_assert(*_get_rule_config(), rule="Basic")

    def test_epsilon_rule_init(self):
        self._rule_assert(*_get_rule_config(), rule="EpsilonInit")

    def test_gamma_rule_function(self):
        self._rule_assert(*_get_rule_config(), rule="GammaFunction")

    def test_alphabeta_rule_function(self):
        self._rule_assert(*_get_rule_config(), rule="Alpha1Beta0")

    def _activations_base_assert(
        self, model, inputs, grads, expected_activations, expected, implementation
    ):
        if implementation == "forward_pass":
            lrp = LRP_0(model)
            activations = lrp._get_activations(inputs)
            assertTensorAlmostEqual(self, activations[3], expected_activations)
        elif implementation == "forward_hook":
            lrp = LRP_0(model)
            lrp._get_activations(inputs)
            assertTensorAlmostEqual(self, *lrp.activations[3], expected_activations)

    def _creator_error_assert(
        self, model, inputs, grads, expected_activations, expected, error
    ):
        if error == "ruleType":
            self.assertRaises(TypeError, LRP, model, [5])
        elif error == "activationType":
            model.add_module("sigmoid", nn.Sigmoid())
            self.assertRaises(TypeError, LRP, model, GammaRule())

    def _get_graph(self, model, image, image2):
        lrp = LRP(model, [Alpha1_Beta0_Rule()])
        lrp._get_graph(image)

    def _simple_attributions(self):
        class Model(nn.Module):
            def __init__(self):
                super(Model, self).__init__()
                self.linear = nn.Linear(3, 3, bias=False)
                self.linear.weight.data.fill_(2.0)
                self.relu = torch.nn.functional.relu
                self.linear2 = nn.Linear(3, 1, bias=False)
                self.linear2.weight.data.fill_(3.0)
            def forward(self, x):
                return self.linear2(self.relu(self.linear(x)))

        model = Model()
        model.eval()
        inputs = torch.tensor([1.0, 2.0, 3.0])
        logits = model(inputs)
        lrp = LRP(model, 3*[Z_Rule()])
        relevance = lrp.attribute(inputs)
        assertTensorAlmostEqual(self, relevance, torch.tensor([18, 36, 54]))

    def _basic_attributions(self, model, inputs, grads, expected_activations, expected):
        logits = model(inputs)
        score, classIndex = torch.max(logits, 1)
        rules = list(repeat(Z_Rule(), 4))
        lrp = LRP(model, rules)
        relevance = lrp.attribute(inputs, classIndex.item(), return_for_all_layers=False)
        self.assertEqual(relevance[0].shape, inputs.shape)
        relevance_sum = torch.sum(relevance[0])
        delta = relevance_sum - score.item()

    def _attributions_assert_vgg(self, model, image, image2):

        classification = model(image)
        score, classIndex = torch.max(classification, 1)
        rules = suggested_rules("vgg16")
        rules = list(repeat(Z_Rule(), 39))
        lrp = LRP(model, rules)
        relevance_all_layers = lrp.attribute(image, classIndex.item(), return_for_all_layers=True)
        relevance = relevance_all_layers[0]
        self.assertEqual(relevance.shape, image.shape)
        relevance_oldImplementation = torch.load("relevance_loopimplementation_zRule.pt")
        relevance_sum = torch.sum(relevance)
        delta = relevance_sum - score.item()
        delta_old = torch.sum(relevance_oldImplementation) - score.item()
        delta_implementation = relevance_oldImplementation - relevance
        delta_sum = torch.sum(delta_implementation)
        old_max = torch.max(relevance_oldImplementation)
        old_min = torch.min(relevance_oldImplementation)
        new_max = torch.max(relevance)
        new_min = torch.min(relevance)
        #relevance = torch.clamp(relevance, -10, 10)

        _ = viz.visualize_image_attr(
            np.transpose(relevance_all_layers[31].data[0].squeeze().cpu().detach().numpy(), (1, 2, 0)),
            np.transpose(image.data[0].squeeze().cpu().detach().numpy(), (1, 2, 0)),
            sign="all",
            method="heat_map",
            cmap="bwr",
        )

    def _rule_assert(self, relevance, layer, activations, input, rule):
        if rule == "BasicPropagate":
            basic = BasicRule()
            propagatedRelevance = basic.propagate(relevance, layer, activations)
            expectedRelevance = torch.tensor([0.0, 1.25, 1.75])
            assertTensorAlmostEqual(self, expectedRelevance, propagatedRelevance)
        elif rule == "Basic":
            basic = BasicRule()
            output = basic.rho(input)
            assertTensorAlmostEqual(self, output, torch.tensor([2, 0, -2]))
        elif rule == "EpsilonInit":
            epsilonRule = EpsilonRhoRule(epsilon=0, rho=math.pow)
            self.assertEqual(epsilonRule.rho(2, 2), 4)
            self.assertEqual(epsilonRule.epsilon, 0)
        elif rule == "GammaFunction":
            gammaRule = GammaRule()
            output = gammaRule.rho(input)
            assertTensorAlmostEqual(self, output, torch.tensor([2.5, 0, -2]))
        elif rule == "Alpha1Beta0":
            alphaBeta = Alpha1_Beta0_Rule()
            output = alphaBeta.rho(input)
            assertTensorAlmostEqual(self, output, torch.tensor([2, 0, 0]))


def _convert_image(path):
    filepath = os.path.join(os.path.dirname(__file__), path)
    image = Image.open(filepath)

    normalize = transforms.Normalize(
        mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
    )
    loader = transforms.Compose(
        [
            transforms.Resize(224),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            normalize,
        ]
    )
    image = loader(image).float()
    image = image.unsqueeze(0)
    return image

