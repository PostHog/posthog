from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.hubspot.auth import HubspotRetryableError, hubspot_refresh_access_token


def _make_response(status: int, payload: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    return response


def _patch_post(response: MagicMock) -> Any:
    session = MagicMock()
    session.post.return_value = response
    return patch(
        "posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    )


@pytest.fixture(autouse=True)
def _no_backoff_sleep() -> Any:
    # hubspot_refresh_access_token backs off on transient errors; skip the real waits in tests.
    with patch("time.sleep"):
        yield


@pytest.mark.parametrize(
    "status,message",
    [
        (429, "You have reached your rate limit."),
        (500, "Internal server error"),
        (502, "Bad gateway"),
        (503, "Service unavailable"),
    ],
)
def test_transient_status_raises_retryable_error(status: int, message: str) -> None:
    with _patch_post(_make_response(status, {"message": message})):
        with pytest.raises(HubspotRetryableError, match=message):
            hubspot_refresh_access_token("refresh-token")


@pytest.mark.parametrize(
    "status,message",
    [
        (400, "missing or invalid refresh token"),
        (401, "unauthorized"),
        (403, "forbidden"),
    ],
)
def test_non_transient_status_raises_plain_exception(status: int, message: str) -> None:
    with _patch_post(_make_response(status, {"message": message})):
        with pytest.raises(Exception) as exc_info:
            hubspot_refresh_access_token("refresh-token")
        assert not isinstance(exc_info.value, HubspotRetryableError)
        assert message in str(exc_info.value)


def test_transient_status_with_non_json_body_still_retryable() -> None:
    response = MagicMock()
    response.status_code = 429
    response.json.side_effect = ValueError("not json")
    response.text = "<html>rate limited</html>"
    with _patch_post(response):
        with pytest.raises(HubspotRetryableError, match="rate limited"):
            hubspot_refresh_access_token("refresh-token")


def test_transient_status_with_message_less_body_still_retryable() -> None:
    response = MagicMock()
    response.status_code = 503
    response.json.return_value = {"error": "unavailable"}
    response.text = "service unavailable"
    with _patch_post(response):
        with pytest.raises(HubspotRetryableError, match="service unavailable"):
            hubspot_refresh_access_token("refresh-token")


def test_success_returns_access_token() -> None:
    with _patch_post(_make_response(200, {"access_token": "new-token"})):
        assert hubspot_refresh_access_token("refresh-token") == "new-token"


def test_transient_status_is_retried_then_succeeds() -> None:
    # A momentary rate limit on the token endpoint should back off and retry rather than
    # fail the whole sync; once HubSpot stops returning 429 the refresh succeeds.
    session = MagicMock()
    session.post.side_effect = [
        _make_response(429, {"message": "You have reached your rate limit."}),
        _make_response(429, {"message": "You have reached your rate limit."}),
        _make_response(200, {"access_token": "new-token"}),
    ]
    with patch(
        "posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        assert hubspot_refresh_access_token("refresh-token") == "new-token"
    assert session.post.call_count == 3


def test_transient_status_reraises_after_exhausting_retries() -> None:
    session = MagicMock()
    session.post.return_value = _make_response(429, {"message": "You have reached your rate limit."})
    with patch(
        "posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        with pytest.raises(HubspotRetryableError, match="You have reached your rate limit."):
            hubspot_refresh_access_token("refresh-token")
    assert session.post.call_count == 5


def test_non_transient_status_is_not_retried() -> None:
    # A non-transient status (e.g. invalid_grant) must surface immediately, not be retried.
    session = MagicMock()
    session.post.return_value = _make_response(400, {"message": "missing or invalid refresh token"})
    with patch(
        "posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        with pytest.raises(Exception) as exc_info:
            hubspot_refresh_access_token("refresh-token")
        assert not isinstance(exc_info.value, HubspotRetryableError)
    assert session.post.call_count == 1
