from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import time_machine
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.google_workspace import GoogleWorkspaceTransientError, raise_if_transient_google_workspace_status


def _response(status_code: int, headers: dict[str, str] | None = None) -> MagicMock:
    return MagicMock(status_code=status_code, headers=headers or {})


class TestGoogleWorkspaceStatusClassification(SimpleTestCase):
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("service_unavailable", 503)])
    def test_transient_status_raises_transient_error_without_the_body(self, _name: str, status_code: int) -> None:
        # A body-free message keeps one failure mode on one error tracking issue.
        with self.assertRaises(GoogleWorkspaceTransientError) as ctx:
            raise_if_transient_google_workspace_status(_response(status_code), "Gmail API")
        assert str(ctx.exception) == f"Gmail API returned {status_code}"

    @parameterized.expand([("bad_request", 400), ("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_permanent_status_is_left_for_the_caller(self, _name: str, status_code: int) -> None:
        assert raise_if_transient_google_workspace_status(_response(status_code), "Gmail API") is None

    def test_retry_after_seconds_is_parsed(self) -> None:
        with self.assertRaises(GoogleWorkspaceTransientError) as ctx:
            raise_if_transient_google_workspace_status(_response(503, {"Retry-After": "30"}), "Gmail API")
        assert ctx.exception.retry_after == timedelta(seconds=30)

    @time_machine.travel("2026-09-11T00:00:00Z", tick=False)
    def test_retry_after_http_date_is_parsed(self) -> None:
        retry_at = datetime(2026, 9, 11, 0, 2, 0, tzinfo=UTC)
        with self.assertRaises(GoogleWorkspaceTransientError) as ctx:
            raise_if_transient_google_workspace_status(
                _response(503, {"Retry-After": format_datetime(retry_at, usegmt=True)}), "Gmail API"
            )
        assert ctx.exception.retry_after == timedelta(minutes=2)

    @parameterized.expand([("missing", {}), ("unparseable", {"Retry-After": "soon"})])
    def test_retry_after_absent_or_unparseable_is_none(self, _name: str, headers: dict[str, str]) -> None:
        with self.assertRaises(GoogleWorkspaceTransientError) as ctx:
            raise_if_transient_google_workspace_status(_response(503, headers), "Gmail API")
        assert ctx.exception.retry_after is None
