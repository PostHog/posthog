from unittest.mock import call

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.hubspot.template_hubspot import template as template_hubspot


class TestTemplateHubspot(BaseHogFunctionTemplateTest):
    template = template_hubspot

    def _inputs(self, **kwargs):
        inputs = {
            "access_token": "TOKEN",
            "email": "example@posthog.com",
            "properties": {
                "company": "PostHog",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.mock_fetch.mock_calls[0] == call(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            {
                "method": "POST",
                "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                "body": {"properties": {"company": "PostHog"}},
            },
        )

        assert self.mock_print.mock_calls[0] == None

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.mock_fetch.mock_calls == []
            assert self.mock_print.mock_calls[0] == call("`email` input is empty. Not creating a contact.")
