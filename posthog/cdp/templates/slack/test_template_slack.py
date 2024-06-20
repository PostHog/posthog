from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.slack.template_slack import template as template_slack


class TestTemplateSlack(BaseHogFunctionTemplateTest):
    template = template_slack

    def test_function_works(self):
        res = self.run_function(
            inputs={
                "slack_workspace": {
                    "access_token": "xoxb-1234",
                },
                "icon_emoji": ":hedgehog:",
                "username": "PostHog",
                "channel": "channel",
                "blocks": [],
            }
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://slack.com/api/chat.postMessage",
            {
                "body": {
                    "channel": "channel",
                    "icon_emoji": ":hedgehog:",
                    "username": "PostHog",
                    "blocks": [],
                    "text": None,
                },
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer xoxb-1234",
                    "Content-Type": "application/json",
                },
            },
        )
