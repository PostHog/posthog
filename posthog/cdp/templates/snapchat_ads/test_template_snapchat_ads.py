from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.snapchat_ads.template_snapchat_ads import (
    template as template_snapchat_ads,
)


class TestTemplateSnapchatAds(BaseHogFunctionTemplateTest):
    template = template_snapchat_ads

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "access_token": "oauth-1234",
            },
            "pixelId": "pixel12345",
            "eventType": "PAGE_VIEW",
            "eventSourceUrl": "https://posthog.com/cdp",
            "eventTime": "1728812163",
            "actionSource": "WEB",
            "userData": {
                "em": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
            },
            "customData": {
                "currency": "USD",
                "price": "1500",
                "event_id": "49ff3d7c-359d-4f45-960e-6cda29f1beea",
            },
            "testEventMode": False,
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            self._inputs(),
            globals={
                "event": {
                    "uuid": "49ff3d7c-359d-4f45-960e-6cda29f1beea",
                    "properties": {
                        "$current_url": "https://posthog.com/cdp",
                    },
                    "event": "$pageview",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://tr.snapchat.com/v3/pixel12345/events?access_token=oauth-1234",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "data": [
                            {
                                "event_name": "PAGE_VIEW",
                                "action_source": "WEB",
                                "event_time": "1728812163",
                                "event_source_url": "https://posthog.com/cdp",
                                "user_data": {"em": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98"},
                                "custom_data": {
                                    "currency": "USD",
                                    "price": "1500",
                                    "event_id": "49ff3d7c-359d-4f45-960e-6cda29f1beea",
                                },
                            }
                        ]
                    },
                },
            )
        )

    def test_test_event_mode(self):
        self.run_function(
            self._inputs(testEventMode=True),
            globals={
                "event": {
                    "uuid": "49ff3d7c-359d-4f45-960e-6cda29f1beea",
                    "properties": {
                        "$current_url": "https://posthog.com/cdp",
                    },
                    "event": "$pageview",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0][0] == snapshot(
            "https://tr.snapchat.com/v3/pixel12345/events/validate?access_token=oauth-1234"
        )

    def test_required_fields(self):
        for config, expected_calls in [
            ({}, 0),
            ({"ph": "1234567890"}, 1),
            ({"em": "1234567890"}, 1),
            ({"client_ip_address": "1234567890", "client_user_agent": "Mozilla/5.0"}, 1),
        ]:
            self.run_function(
                self._inputs(userData=config),
                globals={
                    "event": {
                        "uuid": "49ff3d7c-359d-4f45-960e-6cda29f1beea",
                        "properties": {
                            "$current_url": "https://posthog.com/cdp",
                        },
                        "event": "$pageview",
                    },
                },
            )

            assert len(self.get_mock_fetch_calls()) == expected_calls
