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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_middleware(request: Any, rss_start: float | None, rss_end: float | None) -> list[tuple]:
    """Run per_request_logging_context_middleware and return all logger.warning calls."""
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


# ---------------------------------------------------------------------------
# worker_rss_high
# ---------------------------------------------------------------------------


def test_worker_rss_high_fires_above_threshold():
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=200.0, rss_end=1600.0)
    events = [c[0] for c in calls]
    assert "worker_rss_high" in events


def test_worker_rss_high_silent_below_threshold():
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=200.0, rss_end=1400.0)
    events = [c[0] for c in calls]
    assert "worker_rss_high" not in events


def test_worker_rss_high_includes_request_context():
    request = RequestFactory().post("/api/query/")
    calls = _run_middleware(request, rss_start=200.0, rss_end=1600.0)
    high_calls = [kw for event, kw in calls if event == "worker_rss_high"]
    assert len(high_calls) == 1
    kw = high_calls[0]
    assert kw["rss_mb"] == 1600.0
    assert kw["request_path"] == "/api/query/"
    assert kw["method"] == "POST"


def test_worker_rss_high_includes_team_id_when_present():
    request = RequestFactory().get("/api/test/")
    user = MagicMock()
    user.is_authenticated = True
    user.current_team_id = 42
    request.user = user

    calls = _run_middleware(request, rss_start=200.0, rss_end=1600.0)
    high_calls = [kw for event, kw in calls if event == "worker_rss_high"]
    assert high_calls[0]["team_id"] == 42


def test_worker_rss_high_team_id_none_when_absent():
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=200.0, rss_end=1600.0)
    high_calls = [kw for event, kw in calls if event == "worker_rss_high"]
    assert high_calls[0]["team_id"] is None


def test_worker_rss_high_silent_when_rss_unavailable():
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=None, rss_end=None)
    events = [c[0] for c in calls]
    assert "worker_rss_high" not in events


# ---------------------------------------------------------------------------
# request_memory_growth — team_id
# ---------------------------------------------------------------------------


def test_request_memory_growth_includes_team_id():
    request = RequestFactory().get("/api/test/")
    user = MagicMock()
    user.is_authenticated = True
    user.current_team_id = 99
    request.user = user

    # start=100, end=300 → delta=200, above default 100 MB threshold
    calls = _run_middleware(request, rss_start=100.0, rss_end=300.0)
    growth_calls = [kw for event, kw in calls if event == "request_memory_growth"]
    assert len(growth_calls) == 1
    assert growth_calls[0]["team_id"] == 99


def test_request_memory_growth_team_id_none_when_absent():
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=100.0, rss_end=300.0)
    growth_calls = [kw for event, kw in calls if event == "request_memory_growth"]
    assert len(growth_calls) == 1
    assert growth_calls[0]["team_id"] is None


def test_request_memory_growth_silent_below_threshold():
    request = RequestFactory().get("/api/test/")
    calls = _run_middleware(request, rss_start=100.0, rss_end=150.0)
    events = [c[0] for c in calls]
    assert "request_memory_growth" not in events
