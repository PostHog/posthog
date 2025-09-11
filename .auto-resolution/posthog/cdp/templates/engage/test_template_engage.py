from posthog.cdp.templates.engage.template_engage import template as template_engage
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


class TestTemplateEngageso(BaseHogFunctionTemplateTest):
    template = template_engage

    def _inputs(self, **kwargs):
        inputs = {"public_key": "PUBLIC_KEY", "private_key": "PRIVATE_KEY"}
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        event = self.createHogGlobals()["event"]

        event["event"] = event["name"]

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.engage.so/posthog",
            {
                "method": "POST",
                "headers": {
                    "Authorization": "Basic UFVCTElDX0tFWTpQUklWQVRFX0tFWQ==",
                    "Content-Type": "application/json",
                },
                "body": event,
            },
        )
