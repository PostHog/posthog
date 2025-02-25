from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from inline_snapshot import snapshot

from posthog.cdp.templates.reddit.template_reddit_conversions_api import template_reddit_conversions_api

TEST_EMAIL = "test@example.com"
TEST_PRODUCT_ID = "product12345"
TEST_PIXEL_ID = "pixel12345"
TEST_CONVERSION_ACCESS_TOKEN = "test_access_token"
TEST_EVENT_ID = "0194ff28-77c9-798a-88d5-7225f3d9a5a6"
TEST_EVENT_TIMESTAMP = 1739463203210


class TestTemplateRedditAds(BaseHogFunctionTemplateTest):
    template = template_reddit_conversions_api

    def _inputs(self, **kwargs):
        inputs = {
            "accountId": TEST_PIXEL_ID,
            "conversionAccessToken": TEST_CONVERSION_ACCESS_TOKEN,
            "userProperties": {"email": TEST_EMAIL},
            "eventTime": TEST_EVENT_TIMESTAMP,
        }
        inputs.update(kwargs)
        return inputs

    def test_pageview(self):
        self.run_function(
            self._inputs(
                eventType="PageVisit",
                eventProperties={
                    "conversionId": TEST_EVENT_ID,
                    "products": [{"product_id": TEST_PRODUCT_ID}],
                },
            ),
            globals={
                "event": {
                    "timestamp": TEST_EVENT_TIMESTAMP,
                    # TODO test the default mappings, and provide the rest of the event data
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://ads-api.reddit.com/api/v2.0/conversions/events/pixel12345",
                {
                    "body": {
                        "events": [
                            {
                                "event_at": TEST_EVENT_TIMESTAMP,
                                "event_metadata": {
                                    "conversionId": TEST_EVENT_ID,
                                },
                                "event_type": {"tracking_type": "PageVisit"},
                                "user": {"email": TEST_EMAIL},
                            }
                        ],
                        "test_mode": False,
                    },
                    "headers": {
                        "Authorization": "Bearer ",
                        "Content-Type": "application/json",
                        "User-Agent": "hog:com.posthog.cdp:0.0.1 (by /u/PostHogTeam)",
                    },
                    "method": "POST",
                },
            )
        )
