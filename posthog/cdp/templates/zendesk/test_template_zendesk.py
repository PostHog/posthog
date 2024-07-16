from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.zendesk.template_zendesk import template as template_zendesk


class TestTemplateZendesk(BaseHogFunctionTemplateTest):
    template = template_zendesk

    def test_function_works(self):
        res = self.run_function(
            inputs={"subdomain": "posthog_test", "admin_email": "admin@posthog.com", "token": "TOKEN"}
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://posthog.com",
            {
                "headers": {},
                "body": {"hello": "world"},
                "method": "GET",
            },
        )
