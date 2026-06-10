import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
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
