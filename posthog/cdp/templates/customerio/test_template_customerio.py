from unittest.mock import call
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.customerio.template_customerio import template as template_customerio


class TestTemplateCustomerio(BaseHogFunctionTemplateTest):
    template = template_customerio

    def _inputs(self, **kwargs):
        inputs = {
            "site_id": "SITE_ID",
            "token": "TOKEN",
            "identifier": "ben@posthog.com",
            "host": "track.customer.io",
            "properties": {},
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
