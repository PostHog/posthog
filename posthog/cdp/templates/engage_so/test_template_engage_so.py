from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.engage_so.template_engage_so import template as template_engage_so


class TestTemplateEngageso(BaseHogFunctionTemplateTest):
    template = template_engage_so

    def _inputs(self, **kwargs):
        inputs = {"public_key": "PUBLIC_KEY", "private_key": "PRIVATE_KEY"}
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        event = self.createHogGlobals()["event"]

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.engage.so/posthog",
            {
                "method": "POST",
                "headers": {
                    "Authorization": "Basic UFVCTElDX0tFWTpQUklWQVRFX0tFWQ==",
                    "Content-Type": "application/json",
                },
                "body": {
                    "event": event["name"],
                    "distinct_id": event["distinct_id"],
                    "properties": event["properties"],
                    "person": {"email": "example@posthog.com"},
                },
            },
        )
