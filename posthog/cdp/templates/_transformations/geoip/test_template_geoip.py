from unittest.mock import Mock
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates._transformations.geoip.template_geoip import template as template_geoip


class TestTemplateGeoip(BaseHogFunctionTemplateTest):
    template = template_geoip
    mock_geoip_lookup = Mock()

    def setUp(self):
        super().setUp()
        self.mock_geoip_lookup.return_value = {
            "city": {"names": {"en": "Sydney"}},
            "country": {"names": {"en": "Australia"}},
        }

        self.globals = self.createHogGlobals()
        self.globals["event"]["properties"]["$ip"] = "127.0.0.1"

        self.inputs = {}
        self.functions = {
            "geoipLookup": self.mock_geoip_lookup,
        }

    def test_valid_ip_lookup(self):
        res = self.run_function(inputs=self.inputs, functions=self.functions, globals=self.globals)
        assert res.result != self.globals["event"]
        assert res.result["properties"]["$geoip_city_name"] == "Sydney"

    def test_invalid_ip_lookup(self):
        self.globals["event"]["properties"]["$ip"] = ""
        res = self.run_function(inputs=self.inputs, functions=self.functions, globals=self.globals)
        assert res.result == self.globals["event"]

    def test_invalid_geoip_disabled(self):
        self.globals["event"]["properties"]["$geoip_disable"] = True
        res = self.run_function(inputs=self.inputs, functions=self.functions, globals=self.globals)
        assert res.result == self.globals["event"]
