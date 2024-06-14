from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.webhook.template_webhook import template as template_webhook


class TestTemplateWebhook(BaseHogFunctionTemplateTest):
    template = template_webhook

    def test_function_works(self):
        res = self.run_function(
            inputs={
                "url": "https://posthog.com",
                "method": "GET",
                "headers": {},
                "body": {"hello": "world"},
            }
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://posthog.com",
            {
                "headers": {},
                "body": '{"hello": "world"}',
                "method": "GET",
            },
        )
