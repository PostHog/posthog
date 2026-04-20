import pytest
from freezegun import freeze_time

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.onesignal.template_onesignal import template as template_onesignal

from common.hogvm.python.utils import UncaughtHogVMException


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
                    "OneSignal-Usage": "PostHog | Partner Integration",
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

    def test_function_errors_on_bad_status(self):
        self.fetch_responses = {
            "https://api.onesignal.com/apps/my-app-id/custom_events": {"status": 400, "body": {"error": "error"}}
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(
                inputs={
                    "appId": "my-app-id",
                    "apiKey": "my_secret_key",
                    "externalId": "PERSON_ID",
                    "eventName": "{event.event}",
                    "eventProperties": {},
                    "eventTimestamp": "{event.timestamp}",
                }
            )
        assert "Error sending event" in e.value.message
