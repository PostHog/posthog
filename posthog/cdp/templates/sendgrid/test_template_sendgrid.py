from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.sendgrid.template_sendgrid import template as template_sendgrid


class TestTemplateSendgrid(BaseHogFunctionTemplateTest):
    template = template_sendgrid

    def _inputs(self, **kwargs):
        inputs = {
            "api_key": "API_KEY",
            "email": "example@posthog.com",
            "properties": {"last_name": "example"},
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.sendgrid.com/v3/marketing/contacts",
                {
                    "method": "PUT",
                    "headers": {"Authorization": "Bearer API_KEY", "Content-Type": "application/json"},
                    "body": {"contacts": [{"email": "example@posthog.com", "last_name": "example"}]},
                },
            )
        )

    def test_function_doesnt_include_empty_properties(self):
        res = self.run_function(
            inputs=self._inputs(
                properties={
                    "last_name": "included",
                    "first_name": "",
                    "other": None,
                }
            )
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0][1]["body"]["contacts"] == snapshot(
            [{"email": "example@posthog.com", "last_name": "included"}]
        )
