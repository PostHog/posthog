import json
from unittest.mock import call
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.slack.template_slack import template as template_slack


class TestTemplateSlack(BaseHogFunctionTemplateTest):
    template = template_slack

    def test_function_works(self):
        res = self.run_function(
            inputs={
                "url": "https://posthog.com",
                "method": "GET",
                "headers": {},
                "body": json.dumps({"hello": "world"}),
            }
        )

        assert res.result is None

        assert self.mock_fetch.mock_calls[0] == call(
            "https://posthog.com",
            {
                "headers": {},
                "body": '{"hello": "world"}',
                "method": "GET",
            },
        )
