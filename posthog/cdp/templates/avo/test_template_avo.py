from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.avo.template_avo import template as template_avo


class TestTemplateAvo(BaseHogFunctionTemplateTest):
    template = template_avo

    def _inputs(self, **kwargs):
        inputs = {"api_key": "1234", "environment": "dev"}
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"status": "success"}}  # type: ignore

        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls() == [
            (
                "https://api.hubapi.com/crm/v3/objects/contacts",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
                },
            )
        ]
        assert self.get_mock_print_calls() == [("Contact created successfully!",)]
