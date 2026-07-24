from django.test import SimpleTestCase

from posthog.egress.shopify.limiter import consume_shopify_sync, shopify_store_key


class TestShopifyEgress(SimpleTestCase):
    def test_policy_is_registered_for_the_store_key(self) -> None:
        # consume raises for a domain with no registered policy — this catches the registration
        # side effect being lost (e.g. an import shuffle dropping the register_policy call).
        assert shopify_store_key() == "shopify:store:default"
        assert consume_shopify_sync(source="test") is True
