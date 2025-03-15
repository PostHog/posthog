from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.tiktok_ads.template_tiktok_ads import (
    template as template_tiktok_ads,
)


class TestTemplateTiktokAds(BaseHogFunctionTemplateTest):
    template = template_tiktok_ads

    def _inputs(self, **kwargs):
        inputs = {
            "accessToken": "accessToken12345",
            "pixelId": "123451234512345",
            "eventName": "CompletePayment",
            "eventId": "event-id",
            "eventTimestamp": 1741864319.067,
            "userProperties": {
                "email": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
                "phone": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
            "propertyProperties": {"currency": "USD", "value": 15, "num_items": 2, "order_id": "order-id"},
            "pageProperties": {
                "referrer": "posthog.com",
            },
            "testEventCode": "",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://business-api.tiktok.com/open_api/v1.3/event/track/",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json", "Access-Token": "accessToken12345"},
                    "body": {
                        "event_source": "web",
                        "event_source_id": "123451234512345",
                        "data": [
                            {
                                "event": "CompletePayment",
                                "event_time": 1741864319.067,
                                "event_id": "event-id",
                                "user": {
                                    "email": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
                                    "phone": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                                },
                                "properties": {
                                    "currency": "USD",
                                    "value": 15,
                                    "num_items": 2,
                                    "order_id": "order-id",
                                },
                                "page": {
                                    "referrer": "posthog.com",
                                },
                            }
                        ],
                    },
                },
            )
        )
