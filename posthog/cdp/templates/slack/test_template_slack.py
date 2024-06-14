from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.slack.template_slack import template as template_slack


class TestTemplateSlack(BaseHogFunctionTemplateTest):
    template = template_slack

    def test_function_works(self):
        res = self.run_function(
            inputs={
                "url": "https://webhooks.slack.com/1234",
                "body": {
                    "blocks": [],
                },
            }
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://webhooks.slack.com/1234",
            {
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {"blocks": []},
                "method": "POST",
            },
        )
