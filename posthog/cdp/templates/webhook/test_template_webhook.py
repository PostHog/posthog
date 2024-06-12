import json
from unittest.mock import call
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
                "body": json.dumps({}),
            }
        )

        assert res.result is None

        expected = call(("https://posthog.com",), {"headers": {}, "body": "", "method": "GET"})

        assert self.mock_fetch.call_count == 1
        assert self.mock_fetch.call_args == expected
