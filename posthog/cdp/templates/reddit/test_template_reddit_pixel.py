from posthog.cdp.templates.helpers import BaseSiteDestinationFunctionTest
from posthog.cdp.templates.reddit.template_reddit_pixel import template_reddit_pixel

TEST_EMAIL = "test@example.com"
TEST_PRODUCT_ID = "product12345"
TEST_PIXEL_ID = "pixel12345"


class TestTemplateRedditAds(BaseSiteDestinationFunctionTest):
    template = template_reddit_pixel
    inputs = {
        "pixelId": {
            "value": TEST_PIXEL_ID,
        },
        "userProperties": {
            "value": {"email": "{person.properties.email}"},
        },
    }
    track_fn = "rdt"

    def test_pageview(self):
        event_id, calls = self._process_event("$pageview", {}, {"email": TEST_EMAIL})

        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == ["track", "PageVisit", {"conversion_id": event_id}]

    def test_products_searched(self):
        event_id, calls = self._process_event(
            "Products Searched",
            {
                "products": [{"product_id": TEST_PRODUCT_ID}],
            },
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == ["track", "Search", {"conversion_id": event_id, "products": [{"id": TEST_PRODUCT_ID}]}]

    def test_product_added(self):
        event_id, calls = self._process_event(
            "Product Added",
            {
                "products": [{"product_id": TEST_PRODUCT_ID}],
                "value": 42,
                "currency": "USD",
            },
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "AddToCart",
            {"conversion_id": event_id, "products": [{"id": TEST_PRODUCT_ID}], "currency": "USD", "value": 42},
        ]

    def test_product_added_to_wishlist(self):
        event_id, calls = self._process_event(
            "Product Added to Wishlist",
            {
                "products": [{"product_id": TEST_PRODUCT_ID}],
                "value": 42,
                "currency": "USD",
            },
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "AddToWishlist",
            {"conversion_id": event_id, "products": [{"id": TEST_PRODUCT_ID}], "currency": "USD", "value": 42},
        ]

    def test_product_viewed(self):
        event_id, calls = self._process_event(
            "Product Viewed",
            {
                "products": [{"product_id": TEST_PRODUCT_ID}],
                "value": 42,
                "currency": "USD",
            },
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "ViewContent",
            {"conversion_id": event_id, "products": [{"id": TEST_PRODUCT_ID}], "currency": "USD", "value": 42},
        ]

    def test_purchase(self):
        event_id, calls = self._process_event(
            "Order Completed",
            {
                "products": [{"product_id": TEST_PRODUCT_ID}],
                "value": 42,
                "currency": "USD",
            },
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "Purchase",
            {"conversion_id": event_id, "products": [{"id": TEST_PRODUCT_ID}], "currency": "USD", "value": 42},
        ]

    def test_lead_generated(self):
        event_id, calls = self._process_event(
            "Lead Generated",
            {},
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "Lead",
            {"conversion_id": event_id},
        ]

    def test_signed_up(self):
        event_id, calls = self._process_event(
            "Signed Up",
            {},
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "SignUp",
            {"conversion_id": event_id},
        ]

    def test_event_not_in_spec(self):
        event_id, calls = self._process_event("Event Not In Spec", {}, {"email": TEST_EMAIL})

        assert len(calls) == 1  # Only init call
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
