import pytest

from posthog.temporal.data_imports.sources.shopify.source import ShopifySource


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify GraphQL error: Access denied for fulfillmentOrders field.",
        "Shopify GraphQL error: Access denied for markets field.",
    ],
)
def test_graphql_access_denied_is_non_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"GraphQL access-denied error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify GraphQL error: Throttled",
        "Shopify: internal error from request 500 Internal Server Error",
        "Unexpected graphql response format in Shopify rows read. Keys: ['extensions']",
    ],
)
def test_transient_graphql_errors_stay_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient error '{error_message}' should remain retryable"
    )
