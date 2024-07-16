from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.posthog.template_posthog import template as template_posthog


class TestTemplatePosthog(BaseHogFunctionTemplateTest):
    template = template_posthog

    def test_function_works(self):
        res = self.run_function(
            inputs={
                "host": "https://us.i.posthog.com",
                "token": "TOKEN",
                "include_all_properties": True,
                "properties": {"additional": "value"},
            }
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://us.i.posthog.com/e",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "token": "TOKEN",
                        "event": "event-name",
                        "properties": {"$current_url": "https://example.com", "additional": "value"},
                    },
                },
            )
        )
