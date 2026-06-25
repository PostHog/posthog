import sys
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import RequestFactory

import structlog

from posthog.middleware import current_rss_mb, per_request_logging_context_middleware


@pytest.mark.skipif(sys.platform != "linux", reason="requires /proc (Linux only)")
def test_current_rss_mb_returns_positive_on_linux():
    # On the Linux CI runners /proc/self/statm exists, so this returns the live RSS.
    rss = current_rss_mb()
    # A running Python process always has a non-trivial resident set.
    assert rss is not None
    assert rss > 0


def test_current_rss_mb_handles_missing_proc(monkeypatch):
    # On platforms without /proc (e.g. macOS dev machines) the read fails and we
    # degrade to None rather than raising into the request path.
    def _boom(*_args, **_kwargs):
        raise OSError("no /proc here")

    monkeypatch.setattr("builtins.open", _boom)
    assert current_rss_mb() is None


def _run_middleware(request: Any, rss_start: float | None, rss_end: float | None) -> list[tuple]:
    warning_calls: list[tuple] = []

    def get_response(_request):
        return HttpResponse()

    rss_values = iter([rss_start, rss_end])

    with patch("posthog.middleware.current_rss_mb", side_effect=lambda: next(rss_values)):
        with patch("posthog.middleware.logger") as mock_logger:
            mock_logger.warning.side_effect = lambda event, **kw: warning_calls.append((event, kw))
            try:
                structlog.contextvars.clear_contextvars()
                middleware = per_request_logging_context_middleware(get_response)
                middleware(request)
            finally:
                structlog.contextvars.clear_contextvars()

    return warning_calls


@pytest.mark.parametrize(
    "rss_end,should_fire",
    [
        (1600.0, True),  # above threshold
        (1400.0, False),  # below threshold
        (None, False),  # unavailable on non-Linux
    ],
)
def test_worker_rss_high_threshold(rss_end, should_fire):
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=200.0, rss_end=rss_end)
    fired = any(event == "worker_rss_high" for event, _ in calls)
    assert fired == should_fire


def test_worker_rss_high_team_id_from_authenticated_user():
    # team_id must come from request.user.current_team_id, not request.team
    # (request.team is a viewset cached_property, never set on the request object)
    request = RequestFactory().get("/api/test/")
    user = MagicMock()
    user.is_authenticated = True
    user.current_team_id = 42
    request.user = user

    calls = _run_middleware(request, rss_start=200.0, rss_end=1600.0)
    high = next(kw for event, kw in calls if event == "worker_rss_high")
    assert high["team_id"] == 42


def test_worker_rss_high_team_id_none_for_unauthenticated():
    # AnonymousUser / missing user must not crash and must produce team_id=None
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=200.0, rss_end=1600.0)
    high = next(kw for event, kw in calls if event == "worker_rss_high")
    assert high["team_id"] is None
