from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.salesforce.template_salesforce import (
    template_create as template_salesforce_create,
    template_update as template_salesforce_update,
)


class TestTemplateSlack(BaseHogFunctionTemplateTest):
    template = template_salesforce_create

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "access_token": "oauth-1234",
            },
            "path": "Contact",
            "properties": {
                "foo": "bar",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        res = self.run_function(self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://posthog.my.salesforce.com/services/data/v61.0/sobjects/Contact",
                {
                    "body": {"foo": "bar"},
                    "method": "POST",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )
