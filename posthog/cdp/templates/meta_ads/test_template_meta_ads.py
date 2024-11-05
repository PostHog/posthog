from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.meta_ads.template_meta_ads import (
    template as template_meta_ads,
)


class TestTemplateMetaAds(BaseHogFunctionTemplateTest):
    template = template_meta_ads

    def _inputs(self, **kwargs):
        inputs = {
            "accessToken": "accessToken12345",
            "pixelId": "123451234512345",
            "eventName": "checkout",
            "eventTime": "1728812163",
            "actionSource": "website",
            "userData": {
                "em": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98",
                "fn": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://graph.facebook.com/v21.0/123451234512345/events",
                {
                    "body": {
                        "access_token": "accessToken12345",
                        "data": [
                            {
                                "event_name": "checkout",
                                "event_time": "1728812163",
                                "action_source": "website",
                                "user_data": {"em": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98"},
                            }
                        ],
                    },
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                },
            )
        )
