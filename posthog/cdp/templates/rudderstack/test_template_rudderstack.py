from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.rudderstack.template_rudderstack import template as template_rudderstack


class TestTemplateRudderstack(BaseHogFunctionTemplateTest):
    template = template_rudderstack

    def test_function_works(self):
        self.run_function(
            inputs={
                "host": "https://rudderstack.com",
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
