from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.linkedin_ads.template_linkedin_ads import (
    template as template_linkedin_ads,
)


class TestTemplateLinkedInAds(BaseHogFunctionTemplateTest):
    template = template_linkedin_ads

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "access_token": "oauth-1234",
            },
            "accountId": "account-12345",
            "conversionRuleId": "conversion-rule-12345",
            "conversionDateTime": 1737464596570,
            "conversionValue": "100",
            "currencyCode": "USD",
            "eventId": "event-12345",
            "userIds": {
                "SHA256_EMAIL": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
                "LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID": "abc",
            },
            "userInfo": {"lastName": "AI", "firstName": "Max", "companyName": "PostHog", "countryCode": "US"},
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(self._inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.linkedin.com/rest/conversionEvents",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer oauth-1234",
                        "Content-Type": "application/json",
                        "LinkedIn-Version": "202409",
                    },
                    "body": {
                        "conversion": "urn:lla:llaPartnerConversion:conversion-rule-12345",
                        "conversionHappenedAt": 1737464596570,
                        "user": {
                            "userIds": [
                                {
                                    "idType": "SHA256_EMAIL",
                                    "idValue": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
                                },
                                {"idType": "LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID", "idValue": "abc"},
                            ],
                            "userInfo": {
                                "lastName": "AI",
                                "firstName": "Max",
                                "companyName": "PostHog",
                                "countryCode": "US",
                            },
                        },
                        "eventId": "event-12345",
                        "conversionValue": {"currencyCode": "USD", "amount": "100"},
                    },
                },
            )
        )

    def test_does_not_contain_an_empty_conversion_value_object(self):
        self.run_function(self._inputs(conversionValue=None, currencyCode=None))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.linkedin.com/rest/conversionEvents",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer oauth-1234",
                        "Content-Type": "application/json",
                        "LinkedIn-Version": "202409",
                    },
                    "body": {
                        "conversion": "urn:lla:llaPartnerConversion:conversion-rule-12345",
                        "conversionHappenedAt": 1737464596570,
                        "user": {
                            "userIds": [
                                {
                                    "idType": "SHA256_EMAIL",
                                    "idValue": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
                                },
                                {"idType": "LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID", "idValue": "abc"},
                            ],
                            "userInfo": {
                                "lastName": "AI",
                                "firstName": "Max",
                                "companyName": "PostHog",
                                "countryCode": "US",
                            },
                        },
                        "eventId": "event-12345",
                    },
                },
            )
        )
