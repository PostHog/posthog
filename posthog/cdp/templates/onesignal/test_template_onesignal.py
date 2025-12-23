from freezegun import freeze_time

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.onesignal.template_onesignal import template as template_onesignal


class TestTemplateOneSignal(BaseHogFunctionTemplateTest):
    template = template_onesignal

    @freeze_time("2024-04-16T12:34:51Z")
    def test_function_works(self):
        res = self.run_function(
            inputs={
                "appId": "my-app-id",
                "apiKey": "my_secret_key",
                "externalId": "PERSON_ID",
                "eventName": "{event.event}",
                "eventProperties": {},
                "eventTimestamp": "{event.timestamp}",
            }
        )

        assert res.result is None
        assert self.get_mock_fetch_calls()[0] == (
            "https://api.onesignal.com/apps/my-app-id/custom_events",
            {
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Key my_secret_key",
                },
                "body": {
                    "events": [
                        {
                            "external_id": "PERSON_ID",
                            "name": "{event.event}",
                            "properties": {"$current_url": "https://example.com"},
                            "timestamp": "{event.timestamp}",
                        }
                    ]
                },
                "method": "POST",
            },
        )
