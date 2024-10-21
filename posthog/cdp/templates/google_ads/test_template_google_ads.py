from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.google_ads.template_google_ads import (
    template as template_google_ads,
)


class TestTemplateGoogleAds(BaseHogFunctionTemplateTest):
    template = template_google_ads

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "access_token": "oauth-1234",
            },
            "developerToken": "developer-token1234",
            "customerId": "123-123-1234",
            "conversionActionId": "AW-123456789",
            "gclid": "89y4thuergnjkd34oihroh3uhg39uwhgt9",
            "conversionDateTime": "2024-10-10 16:32:45+02:00",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://googleads.googleapis.com/v17/customers/1231231234:uploadClickConversions",
                {
                    "body": {
                        "conversions": [
                            {
                                "gclid": "89y4thuergnjkd34oihroh3uhg39uwhgt9",
                                "conversionAction": f"customers/1231231234/conversionActions/123456789",
                                "conversionDateTime": "2024-10-10 16:32:45+02:00",
                            }
                        ],
                        "partialFailure": True,
                        "validateOnly": True,
                    },
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer oauth-1234",
                        "Content-Type": "application/json",
                        "developer-token": "developer-token1234",
                    },
                },
            )
        )
