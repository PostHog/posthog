from posthog.cdp.templates.helpers import BaseSiteDestinationFunctionTest
from posthog.cdp.templates.reddit.template_reddit_pixel import template_reddit_pixel


class TestTemplateRedditAds(BaseSiteDestinationFunctionTest):
    template = template_reddit_pixel
    inputs = {
        "pixelId": {
            "value": "pixel12345",
        },
        "userProperties": {
            "value": {"email": "{person.properties.email}"},
        },
    }
    window_fn = "rdt"

    def test_pageview(self):
        email = "test@example.com"
        event_id, calls = self._process_event("$pageview", {}, {"email": email})

        assert len(calls) == 2
        assert calls[0] == ["init", "pixel12345", {"email": email}]
        assert calls[1] == ["track", "PageVisit", {"conversion_id": event_id}]
