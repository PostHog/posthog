import json
from unittest.mock import call
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.hubspot.template_hubspot import template as template_hubspot


class TestTemplateHubspot(BaseHogFunctionTemplateTest):
    template = template_hubspot

    def _inputs(self, **kwargs):
        inputs = {
            "url": "https://posthog.com",
            "method": "GET",
            "headers": {},
            "body": json.dumps({"hello": "world"}),
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.mock_fetch.mock_calls[0] == call(
            "https://posthog.com",
            {
                "headers": {},
                "body": '{"hello": "world"}',
                "method": "GET",
            },
        )
