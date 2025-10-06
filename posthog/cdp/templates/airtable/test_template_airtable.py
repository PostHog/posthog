from inline_snapshot import snapshot

from posthog.cdp.templates.airtable.template_airtable import template as template_airtable
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


class TestTemplateAirtable(BaseHogFunctionTemplateTest):
    template = template_airtable

    def test_function_works(self):
        self.run_function(
            inputs={
                "access_token": "test_token",
                "base_id": "test_base_id",
                "table_name": "test_table",
                "fields": {"Name": "John Doe", "Email": "john@example.com"},
                "debug": False,
            }
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.airtable.com/v0/test_base_id/test_table",
                {
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer test_token"},
                    "body": {"fields": {"Name": "John Doe", "Email": "john@example.com"}, "typecast": True},
                    "method": "POST",
                },
            )
        )
        assert self.get_mock_print_calls() == snapshot([])

    def test_prints_when_debugging(self):
        self.run_function(
            inputs={
                "access_token": "test_token",
                "base_id": "test_base_id",
                "table_name": "test_table",
                "fields": {"Name": "John Doe", "Email": "john@example.com"},
                "debug": True,
            }
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.airtable.com/v0/test_base_id/test_table",
                {
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer test_token"},
                    "body": {"fields": {"Name": "John Doe", "Email": "john@example.com"}, "typecast": True},
                    "method": "POST",
                },
            )
        )
        assert self.get_mock_print_calls() == snapshot(
            [
                (
                    "Request",
                    "https://api.airtable.com/v0/test_base_id/test_table",
                    {
                        "headers": {"Content-Type": "application/json", "Authorization": "Bearer test_token"},
                        "body": {"fields": {"Name": "John Doe", "Email": "john@example.com"}, "typecast": True},
                        "method": "POST",
                    },
                ),
                ("Response", 200, {}),
            ]
        )
