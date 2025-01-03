from unittest.mock import Mock
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates._transformations.downsample.template_downsample import template as template_downsample


class TestTemplateDownsample(BaseHogFunctionTemplateTest):
    template = template_downsample
    mock_randCanonical = Mock()

    def setUp(self):
        super().setUp()
        self.mock_randCanonical.return_value = 1

        self.globals = self.createHogGlobals()

        self.inputs = {
            "percentage": 50,
            "samplingMethod": "random",
        }
        self.functions = {
            "randCanonical": self.mock_randCanonical,
        }

    def test_random_sampling(self):
        self.mock_randCanonical.return_value = 0
        res = self.run_function(inputs=self.inputs, functions=self.functions)
        assert res.result == self.createHogGlobals()["event"]

        self.mock_randCanonical.return_value = 0.50
        res = self.run_function(inputs=self.inputs, functions=self.functions)
        assert res.result == self.createHogGlobals()["event"]

        self.mock_randCanonical.return_value = 0.51
        res = self.run_function(inputs=self.inputs, functions=self.functions)
        assert res.result is None

        self.mock_randCanonical.return_value = 1
        res = self.run_function(inputs=self.inputs, functions=self.functions)
        assert res.result is None

    def test_distinct_id_sampling(self):
        # distinct-id hashes to a number between 0 and 1152921504606846975
        self.inputs["samplingMethod"] = "distinct_id"
        self.mock_randCanonical.return_value = 0
        res = self.run_function(inputs=self.inputs, functions=self.functions)
        assert res.result == self.createHogGlobals()["event"]

        self.mock_randCanonical.return_value = 1
        res = self.run_function(inputs=self.inputs, functions=self.functions)
        assert res.result == self.createHogGlobals()["event"]
