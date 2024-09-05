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

    def test_function_adds_custom_fields(self):
        self.mock_fetch_response = lambda *args: {
            "status": 200,
            "body": {"custom_fields": [{"id": "id7", "name": "custom_field"}]},
        }

        res = self.run_function(
            inputs=self._inputs(
                custom_fields={"custom_field": "custom_value"},
            )
        )
        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.sendgrid.com/v3/marketing/field_definitions",
                {
                    "method": "GET",
                    "headers": {"Authorization": "Bearer API_KEY", "Content-Type": "application/json"},
                },
            )
        )

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.sendgrid.com/v3/marketing/contacts",
                {
                    "method": "PUT",
                    "headers": {"Authorization": "Bearer API_KEY", "Content-Type": "application/json"},
                    "body": {
                        "contacts": [
                            {
                                "email": "example@posthog.com",
                                "last_name": "example",
                                "custom_fields": {"id7": "custom_value"},
                            }
                        ]
                    },
                },
            )
        )
