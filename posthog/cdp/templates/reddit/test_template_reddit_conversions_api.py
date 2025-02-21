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
            "userProperties": {"email": "{person.properties.email}"},
        }
        inputs.update(kwargs)
        return inputs

    def test_pageview(self):
        self.run_function(
            self._inputs(),
            globals={
                "event": {
                    "uuid": TEST_EVENT_ID,
                    "timestamp": TEST_EVENT_TIMESTAMP,
                    "properties": {
                        "$current_url": "https://posthog.com/cdp",
                    },
                    "event": "$pageview",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://ads-api.reddit.com/api/v2.0/conversions/events/pixel12345",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "events": [
                            {
                                "event_name": "PageView",
                                "event_at": 1739463203210,
                                "user_data": {"em": "3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98"},
                                "event_metadata": {
                                    "conversion_id": "0194ff28-77c9-798a-88d5-7225f3d9a5a6",
                                },
                            }
                        ]
                    },
                },
            )
        )

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

    def test_product_from_top_level_properties(self):
        event_id, calls = self._process_event(
            "Product Added",
            {
                "product_id": TEST_PRODUCT_ID,
                "name": "Product Name",
                "category": "Product Category",
                "price": 42,
                "currency": "USD",
            },
            {"email": TEST_EMAIL},
        )
        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "AddToCart",
            {
                "conversion_id": event_id,
                "products": [{"id": TEST_PRODUCT_ID, "name": "Product Name", "category": "Product Category"}],
                "currency": "USD",
                "value": 42,
            },
        ]

    def test_custom_event(self):
        def add_custom_mapping(payload):
            payload["mappings"].append(
                {
                    "filters": {"events": [{"id": "Event Not In Spec", "name": "Event Not In Spec", "type": "events"}]},
                    "inputs": {
                        "eventType": {"value": "Mapped Event Not In Spec"},
                        "eventProperties": {
                            "value": {
                                "conversion_id": "{event.uuid}",
                                "products": "{event.properties.products ? arrayMap(product -> ({'id': product.product_id, 'category': product.category, 'name': product.name}), event.properties.products) : event.properties.product_id ? [{'id': event.properties.product_id, 'category': event.properties.category, 'name': event.properties.name}] : undefined}",
                                "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
                                "currency": "{event.properties.currency}",
                            }
                        },
                    },
                    "inputs_schema": [
                        {
                            "key": "eventType",
                            "type": "string",
                            "label": "Event Type",
                            "description": "description",
                            "default": "Mapped Event Not In Spec",
                            "required": True,
                        },
                        {
                            "key": "eventProperties",
                            "type": "dictionary",
                            "description": "description",
                            "label": "Event parameters",
                            "default": {
                                "conversion_id": "{event.uuid}",
                                "products": "{event.properties.products ? arrayMap(product -> ({'id': product.product_id, 'category': product.category, 'name': product.name}), event.properties.products) : event.properties.product_id ? [{'id': event.properties.product_id, 'category': event.properties.category, 'name': event.properties.name}] : undefined}",
                                "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
                                "currency": "{event.properties.currency}",
                            },
                            "secret": False,
                            "required": False,
                        },
                    ],
                    "name": "Event Not In Spec",
                },
            )
            return payload

        event_id, calls = self._process_event(
            "Event Not In Spec",
            {},
            {"email": TEST_EMAIL},
            edit_payload=add_custom_mapping,
        )

        assert len(calls) == 2
        assert calls[0] == ["init", TEST_PIXEL_ID, {"email": TEST_EMAIL}]
        assert calls[1] == [
            "track",
            "Custom",
            {
                "conversion_id": event_id,
                "customEventName": "Mapped Event Not In Spec",
            },
        ]
