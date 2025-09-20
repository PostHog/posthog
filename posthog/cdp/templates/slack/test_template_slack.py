import pytest

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.slack.template_slack import template as template_slack

from common.hogvm.python.utils import UncaughtHogVMException


class TestTemplateSlack(BaseHogFunctionTemplateTest):
    template = template_slack

    def _inputs(self, **kwargs):
        inputs = {
            "slack_workspace": {
                "access_token": "xoxb-1234",
            },
            "icon_emoji": ":hedgehog:",
            "username": "PostHog",
            "channel": "channel",
            "blocks": [],
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        res = self.run_function(self._inputs())

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

        assert self.get_mock_print_calls() == []

    def test_function_prints_warning_on_bad_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"ok": True}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs())

        assert e.value.message == "Failed to post message to Slack: 400: {'ok': true}"

    def test_function_prints_warning_on_bad_body(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": False}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs())
        assert e.value.message == "Failed to post message to Slack: 200: {'ok': false}"
