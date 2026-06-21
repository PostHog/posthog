import pytest

from tenacity import Future, RetryCallState

from posthog.temporal.data_imports.sources.shopify.shopify import (
    _SHOPIFY_MAX_THROTTLE_WAIT_SECONDS,
    ShopifyRetryableError,
    _get_retryable_error,
    _shopify_retry_wait,
    _throttle_retry_after,
)


def _throttled_payload(requested: float, available: float, restore_rate: float) -> dict:
    return {
        "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
        "extensions": {
            "cost": {
                "requestedQueryCost": requested,
                "throttleStatus": {
                    "maximumAvailable": 2000,
                    "currentlyAvailable": available,
                    "restoreRate": restore_rate,
                },
            }
        },
    }


def _retry_state(exc: Exception) -> RetryCallState:
    state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
    state.outcome = Future.construct(1, exc, True)
    return state


def test_throttle_retry_after_computes_refill_time():
    # deficit 90 points at 50/sec => 1.8s
    assert _throttle_retry_after(_throttled_payload(100, 10, 50)) == pytest.approx(1.8)


def test_throttle_retry_after_is_capped():
    # An enormous deficit (or tiny restore rate) must not stall the worker indefinitely.
    assert _throttle_retry_after(_throttled_payload(10_000, 0, 1)) == _SHOPIFY_MAX_THROTTLE_WAIT_SECONDS


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"extensions": {}},
        {"extensions": {"cost": {"requestedQueryCost": 100}}},
        {"extensions": {"cost": {"requestedQueryCost": 100, "throttleStatus": {"currentlyAvailable": 10}}}},
        # restoreRate of 0 would divide by zero
        _throttled_payload(100, 10, 0),
        # bucket already has enough headroom
        _throttled_payload(100, 200, 50),
    ],
)
def test_throttle_retry_after_returns_none_when_unavailable(payload):
    assert _throttle_retry_after(payload) is None


def test_get_retryable_error_attaches_retry_after():
    error = _get_retryable_error(_throttled_payload(100, 10, 50))
    assert isinstance(error, ShopifyRetryableError)
    assert error.retry_after == pytest.approx(1.8)


def test_get_retryable_error_throttled_without_cost_has_no_retry_after():
    error = _get_retryable_error({"errors": [{"message": "Throttled"}]})
    assert isinstance(error, ShopifyRetryableError)
    assert error.retry_after is None


def test_retry_wait_honors_throttle_refill_time():
    # The exponential floor is ~1s on the first attempt; Shopify's refill time must win.
    wait = _shopify_retry_wait(_retry_state(ShopifyRetryableError("rate limit", retry_after=20.0)))
    assert wait >= 20.0


def test_retry_wait_falls_back_to_backoff_without_retry_after():
    wait = _shopify_retry_wait(_retry_state(ShopifyRetryableError("internal error")))
    assert wait > 0
