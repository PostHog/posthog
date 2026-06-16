import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
    SHOPIFY_PAYMENT_REQUIRED_ERROR,
    _get_shopify_access_token,
)
from posthog.temporal.data_imports.sources.shopify.source import ShopifySource


def _mock_response(status_code: int, ok: bool, json_data: dict | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.json.return_value = json_data or {}
    return response


def _patched_token_call(response: mock.MagicMock):
    return mock.patch(
        "posthog.temporal.data_imports.sources.shopify.shopify.make_tracked_session",
        return_value=mock.MagicMock(post=mock.MagicMock(return_value=response)),
    )


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_get_access_token_4xx_is_non_retryable(status_code):
    with _patched_token_call(_mock_response(status_code, ok=False)):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    assert SHOPIFY_ACCESS_TOKEN_AUTH_ERROR in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"4xx token error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_get_access_token_transient_stays_retryable(status_code):
    with _patched_token_call(_mock_response(status_code, ok=False)):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient token error '{error_message}' should remain retryable"
    )


def test_get_access_token_success_returns_token():
    with _patched_token_call(_mock_response(200, ok=True, json_data={"access_token": "tok"})):
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify GraphQL error: Access denied for fulfillmentOrders field.",
        "Shopify GraphQL error: Access denied for paymentTerms field. Required access: `read_payment_terms` access scope.",
        "Shopify GraphQL error: Access denied for orders field.; Access denied for paymentTerms field.",
    ],
)
def test_graphql_access_denied_is_non_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"GraphQL access-scope error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "402 Client Error: Payment Required for url: https://my-store.myshopify.com/admin/api/2025-10/graphql.json",
        "402 Client Error: Payment Required for url: https://another-store.myshopify.com/admin/api/2024-01/graphql.json",
    ],
)
def test_payment_required_is_non_retryable(error_message):
    assert SHOPIFY_PAYMENT_REQUIRED_ERROR in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"402 Payment Required error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify: rate limit exceeded...",
        "Shopify: internal error from request 503 Service Unavailable",
        "Unexpected graphql response format in Shopify rows read. Keys: ['extensions']",
        "429 Client Error: Too Many Requests for url: https://my-store.myshopify.com/admin/api/2025-10/graphql.json",
    ],
)
def test_transient_graphql_errors_stay_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient error '{error_message}' should remain retryable"
    )
