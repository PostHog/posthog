from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

from posthog.tasks.alerts import schedule_restriction as schedule_restriction_module
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked, next_unblocked_utc
from posthog.tasks.alerts.utils import next_check_at_after_schedule_restriction_change

from products.alerts.backend.models.alert import AlertConfiguration


class TestIsUtcDatetimeBlockedAndNextUnblocked:
    def _alert(self, tz: str, restriction: dict[str, Any] | None) -> MagicMock:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "test-id"
        alert.team = MagicMock()
        alert.team.timezone = tz
        alert.schedule_restriction = restriction
        return alert

    def test_is_blocked_reads_alert_timezone_and_restriction(self) -> None:
        alert = self._alert(
            "America/Los_Angeles",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        assert is_utc_datetime_blocked(alert, datetime(2024, 6, 1, 18, 0, tzinfo=UTC)) is True

    def test_next_unblocked_advances_to_end_of_window(self) -> None:
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        fro = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
        nxt = next_unblocked_utc(alert, fro)
        assert nxt == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

    def test_next_unblocked_retries_and_logs_when_scan_hits_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(schedule_restriction_module, "_MAX_UNBLOCK_STEPS", 5)
        warning = MagicMock()
        error = MagicMock()
        monkeypatch.setattr(schedule_restriction_module.logger, "warning", warning)
        monkeypatch.setattr(schedule_restriction_module.logger, "error", error)
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        fro = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
        nxt = next_unblocked_utc(alert, fro)
        assert nxt == datetime(2024, 6, 3, 11, 0, tzinfo=UTC)
        assert warning.call_count == 2
        warning.assert_any_call(
            "schedule_restriction.next_unblocked_utc_exceeded_cap",
            alert_id="test-id",
            recursion_depth=0,
        )
        error.assert_called_once_with(
            "schedule_restriction.next_unblocked_utc_giving_up_after_retry",
            alert_id="test-id",
        )


class TestNextCheckAtAfterScheduleRestrictionChange:
    def _hourly_alert(self, **kwargs: Any) -> MagicMock:
        alert = MagicMock(spec=AlertConfiguration)
        alert.team = MagicMock()
        alert.team.timezone = "UTC"
        alert.calculation_interval = "hourly"
        for k, v in kwargs.items():
            setattr(alert, k, v)
        return alert

    def test_cleared_restriction_schedules_from_now_and_restores_existing_value(self) -> None:
        with freeze_time("2026-04-06T14:00:00Z"):
            existing = datetime(2026, 4, 7, 18, 30, tzinfo=UTC)
            alert = self._hourly_alert(schedule_restriction=None, next_check_at=existing)
            out = next_check_at_after_schedule_restriction_change(alert)
            assert out == datetime(2026, 4, 6, 15, 0, 0, tzinfo=UTC)
            assert alert.next_check_at == existing

    def test_future_next_check_inside_blocked_window_snaps_to_first_unblocked_minute(self) -> None:
        with freeze_time("2026-04-06T14:00:00Z"):
            alert = self._hourly_alert(
                schedule_restriction={"blocked_windows": [{"start": "11:00", "end": "16:00"}]},
                next_check_at=datetime(2026, 4, 6, 15, 30, tzinfo=UTC),
            )
            out = next_check_at_after_schedule_restriction_change(alert)
            assert out == datetime(2026, 4, 6, 16, 0, 0, tzinfo=UTC)

    def test_does_not_keep_stale_snap_when_earlier_runs_are_allowed(self) -> None:
        with freeze_time("2026-04-06T16:44:00Z"):
            alert = self._hourly_alert(
                team=MagicMock(timezone="America/Toronto"),
                schedule_restriction={"blocked_windows": [{"start": "14:00", "end": "16:00"}]},
                next_check_at=datetime(2026, 4, 6, 20, 0, 0, tzinfo=UTC),
            )
            out = next_check_at_after_schedule_restriction_change(alert)
            assert out == datetime(2026, 4, 6, 17, 44, 0, tzinfo=UTC)
