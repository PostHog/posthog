from unittest.mock import call
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.customerio.template_customerio import template as template_customerio


class TestTemplateCustomerio(BaseHogFunctionTemplateTest):
    template = template_customerio

    def _inputs(self, **kwargs):
        inputs = {
            "site_id": "SITE_ID",
            "token": "TOKEN",
            "identifier": "example@posthog.com",
            "host": "track.customer.io",
            "properties": {"name": "example"},
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://track.customer.io/api/v2/entity",
            {
                "method": "POST",
                "headers": {
                    "User-Agent": "PostHog Customer.io App",
                    "Authorization": "Basic SITE_ID:TOKEN",
                    "Content-Type": "application/json",
                },
                "body": {
                    "type": "person",
                    "identifiers": {"id": "example@posthog.com"},
                    "action": "identify",
                    "attributes": {
                        "name": "example",
                    },
                },
            },
        )
