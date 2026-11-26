from products.customer_analytics.backend.logic.posthog_product_usage import AGENT_PRODUCT_KEYS, POSTHOG_PRODUCTS


def test_every_agent_rule_targets_a_known_product() -> None:
    assert AGENT_PRODUCT_KEYS <= {product.key for product in POSTHOG_PRODUCTS}
