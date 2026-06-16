from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.temporal.data_imports.sources.hubspot.auth import HubspotRetryableError, hubspot_refresh_access_token


def _make_response(status: int, payload: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    return response


def _patch_post(responses: MagicMock | list[MagicMock | BaseException]) -> Any:
    """Patch make_tracked_session and return (patcher, session).

    A single response is returned for every POST; a list is consumed one per call via side_effect,
    with exception instances raised automatically (mirroring requests failures).
    """
    session = MagicMock()
    if isinstance(responses, list):
        session.post.side_effect = responses
    else:
        session.post.return_value = responses
    patcher = patch(
        "posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    )
    return patcher, session


@pytest.fixture(autouse=True)
def _no_retry_sleep() -> Iterator[None]:
    # The token refresh is wrapped in tenacity backoff; skip real sleeps so retry tests stay fast.
    original = hubspot_refresh_access_token.retry.sleep
    hubspot_refresh_access_token.retry.sleep = lambda _: None
    yield
    hubspot_refresh_access_token.retry.sleep = original


@pytest.mark.parametrize(
    "status,message",
    [
        (429, "You have reached your rate limit."),
        (500, "Internal server error"),
        (502, "Bad gateway"),
        (503, "Service unavailable"),
    ],
)
def test_transient_status_exhausts_retries_then_raises_retryable_error(status: int, message: str) -> None:
    # A persistently transient status backs off across all attempts and stays retryable.
    patcher, session = _patch_post(_make_response(status, {"message": message}))
    with patcher:
        with pytest.raises(HubspotRetryableError, match=message):
            hubspot_refresh_access_token("refresh-token")
    assert session.post.call_count == 5


@pytest.mark.parametrize(
    "first_failure",
    [
        _make_response(429, {"message": "You have reached your rate limit."}),
        _make_response(503, {"message": "Service unavailable"}),
        requests.ConnectionError("boom"),
    ],
)
def test_transient_failure_then_success_is_retried(first_failure: Any) -> None:
    patcher, session = _patch_post([first_failure, _make_response(200, {"access_token": "new-token"})])
    with patcher:
        assert hubspot_refresh_access_token("refresh-token") == "new-token"
    assert session.post.call_count == 2


@pytest.mark.parametrize(
    "status,message",
    [
        (400, "missing or invalid refresh token"),
        (401, "unauthorized"),
        (403, "forbidden"),
    ],
)
def test_non_transient_status_fails_fast_with_plain_exception(status: int, message: str) -> None:
    patcher, session = _patch_post(_make_response(status, {"message": message}))
    with patcher:
        with pytest.raises(Exception) as exc_info:
            hubspot_refresh_access_token("refresh-token")
    assert not isinstance(exc_info.value, HubspotRetryableError)
    assert message in str(exc_info.value)
    assert session.post.call_count == 1


def test_transient_status_with_non_json_body_still_retryable() -> None:
    response = MagicMock()
    response.status_code = 429
    response.json.side_effect = ValueError("not json")
    response.text = "<html>rate limited</html>"
    patcher, _ = _patch_post(response)
    with patcher:
        with pytest.raises(HubspotRetryableError, match="rate limited"):
            hubspot_refresh_access_token("refresh-token")


def test_transient_status_with_message_less_body_still_retryable() -> None:
    response = MagicMock()
    response.status_code = 503
    response.json.return_value = {"error": "unavailable"}
    response.text = "service unavailable"
    patcher, _ = _patch_post(response)
    with patcher:
        with pytest.raises(HubspotRetryableError, match="service unavailable"):
            hubspot_refresh_access_token("refresh-token")


def test_success_returns_access_token() -> None:
    patcher, session = _patch_post(_make_response(200, {"access_token": "new-token"}))
    with patcher:
        assert hubspot_refresh_access_token("refresh-token") == "new-token"
    assert session.post.call_count == 1
