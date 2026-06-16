from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.hubspot.auth import HubspotRetryableError, hubspot_refresh_access_token


def _make_response(status: int, payload: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.json.return_value = payload or {}
    return response


def _session_returning(responses: list[MagicMock]) -> Any:
    post = MagicMock(side_effect=responses)
    session = MagicMock()
    session.post = post
    return lambda *_a, **_k: session, post


@pytest.fixture(autouse=True)
def _no_backoff_sleep() -> Any:
    # tenacity sleeps between retries; neutralise it so the test is fast.
    # `.retry` is attached by tenacity's @retry decorator at runtime; mypy can't see it.
    retrying = cast(Any, hubspot_refresh_access_token).retry
    original_sleep = retrying.sleep
    retrying.sleep = lambda *_a, **_k: None
    yield
    retrying.sleep = original_sleep


class TestHubspotRefreshAccessToken:
    @pytest.mark.parametrize(
        "status_code,message",
        [
            (429, "You have reached your rate limit."),
            (503, "service unavailable"),
        ],
    )
    def test_retryable_error_is_retried_then_succeeds(self, status_code: int, message: str) -> None:
        make_session, post = _session_returning(
            [
                _make_response(status_code, {"message": message}),
                _make_response(200, {"access_token": "fresh-token"}),
            ]
        )
        with patch("posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session", new=make_session):
            token = hubspot_refresh_access_token("refresh-token")

        assert token == "fresh-token"
        assert post.call_count == 2

    def test_persistent_429_reraises_retryable_error_after_exhausting_attempts(self) -> None:
        make_session, post = _session_returning(
            [_make_response(429, {"message": "You have reached your rate limit."}) for _ in range(5)]
        )
        with patch("posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session", new=make_session):
            with pytest.raises(HubspotRetryableError):
                hubspot_refresh_access_token("refresh-token")

        assert post.call_count == 5

    def test_4xx_non_rate_limit_raises_message_without_retry(self) -> None:
        # A genuine client error (e.g. revoked/invalid refresh token) is not transient: it must
        # surface the HubSpot message immediately so the existing non-retryable handling kicks in.
        make_session, post = _session_returning([_make_response(400, {"message": "missing or invalid refresh token"})])
        with patch("posthog.temporal.data_imports.sources.hubspot.auth.make_tracked_session", new=make_session):
            with pytest.raises(Exception, match="missing or invalid refresh token") as exc_info:
                hubspot_refresh_access_token("refresh-token")

        assert not isinstance(exc_info.value, HubspotRetryableError)
        assert post.call_count == 1
