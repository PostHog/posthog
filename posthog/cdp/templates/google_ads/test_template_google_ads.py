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
            "customerId": "1231231234/5675675678",
            "conversionActionId": "123456789",
            "gclid": "89y4thuergnjkd34oihroh3uhg39uwhgt9",
            "conversionDateTime": "2024-10-10 16:32:45+02:00",
            "currencyCode": "USD",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(self._inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://googleads.googleapis.com/v18/customers/1231231234:uploadClickConversions",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer oauth-1234",
                        "Content-Type": "application/json",
                        "login-customer-id": "5675675678",
                    },
                    "body": {
                        "conversions": [
                            {
                                "gclid": "89y4thuergnjkd34oihroh3uhg39uwhgt9",
                                "conversion_action": f"customers/1231231234/conversionActions/123456789",
                                "conversion_date_time": "2024-10-10 16:32:45+02:00",
                                "currency_code": "USD",
                            }
                        ],
                        "partialFailure": True,
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(self._inputs(gclid=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("Empty `gclid`. Skipping...",)])
