from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.loops.template_loops import template as template_loops


class TestTemplateLoops(BaseHogFunctionTemplateTest):
    template = template_loops

    def _inputs(self, **kwargs):
        inputs = {"apiKey": "1cac089e00a708680bdb1ed9f082d5bf"}
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self._inputs(),
            globals={
                "event": {"distinct_id": "66e614bd-d9f2-491e-9e2c-eeab3090f72f", "name": "$pageview"},
                "person": {
                    "properties": {"email": "max@posthog.com", "name": "Max", "company": "PostHog"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://app.loops.so/api/v1/events/send",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer 1cac089e00a708680bdb1ed9f082d5bf",
                    },
                    "body": {
                        "userId": "66e614bd-d9f2-491e-9e2c-eeab3090f72f",
                        "eventName": "$pageview",
                        "email": "max@posthog.com",
                        "name": "Max",
                        "company": "PostHog",
                    },
                },
            )
        )

    def test_automatic_action_mapping(self):
        for event_name, expected_action in [
            ("$identify", "$identify"),
            ("$set", "$identify"),
            ("$pageview", "$pageview"),
            ("$create_alias", "$create_alias"),
            ("$autocapture", "$autocapture"),
            ("custom", "custom"),
        ]:
            self.run_function(
                inputs=self._inputs(),
                globals={
                    "event": {"name": event_name, "properties": {"url": "https://example.com", "$browser": "Chrome"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["eventName"] == expected_action
