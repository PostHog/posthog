from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.posthog.template_posthog import template as template_posthog


class TestTemplatePosthog(BaseHogFunctionTemplateTest):
    template = template_posthog

    def test_function_works(self):
        self.run_function(
            inputs={
                "host": "https://us.i.posthog.com",
                "token": "TOKEN",
                "include_all_properties": True,
                "properties": {"additional": "value"},
            }
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://us.i.posthog.com/e",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "token": "TOKEN",
                        "event": "event-name",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "distinct_id": "distinct-id",
                        "properties": {"$current_url": "https://example.com", "additional": "value"},
                    },
                },
            )
        )

    def test_function_doesnt_include_all_properties(self):
        self.run_function(
            inputs={
                "host": "https://us.i.posthog.com",
                "token": "TOKEN",
                "include_all_properties": False,
                "properties": {"additional": "value"},
            }
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["properties"] == snapshot({"additional": "value"})
