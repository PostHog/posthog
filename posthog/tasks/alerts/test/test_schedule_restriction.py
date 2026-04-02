from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.models import AlertConfiguration
from posthog.tasks.alerts import schedule_restriction as schedule_restriction_module
from posthog.tasks.alerts.schedule_restriction import (
    is_utc_datetime_blocked,
    next_unblocked_utc,
    validate_and_normalize_schedule_restriction,
)


class TestValidateAndNormalizeScheduleRestriction:
    @parameterized.expand(
        [
            (None, None),
            ({}, None),
            ({"blocked_windows": []}, None),
            (
                {"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
                {"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
            ),
        ]
    )
    def test_normalize_feature_off_or_valid_overnight(self, raw: Any, expected: dict[str, Any] | None) -> None:
        assert validate_and_normalize_schedule_restriction(raw) == expected

    def test_merges_overlapping_same_day_windows(self) -> None:
        raw = {
            "blocked_windows": [
                {"start": "10:30", "end": "11:00"},
                {"start": "10:40", "end": "11:15"},
            ]
        }
        out = validate_and_normalize_schedule_restriction(raw)
        assert out == {"blocked_windows": [{"start": "10:30", "end": "11:15"}]}

    def test_adjacent_half_open_windows_merge(self) -> None:
        raw = {
            "blocked_windows": [
                {"start": "12:00", "end": "13:00"},
                {"start": "13:00", "end": "14:00"},
            ]
        }
        out = validate_and_normalize_schedule_restriction(raw)
        assert out == {"blocked_windows": [{"start": "12:00", "end": "14:00"}]}

    def test_rejects_full_day_coverage(self) -> None:
        raw = {
            "blocked_windows": [
                {"start": "00:00", "end": "12:00"},
                {"start": "12:00", "end": "00:00"},
            ]
        }
        with pytest.raises(ValueError, match="at least one time"):
            validate_and_normalize_schedule_restriction(raw)

    def test_rejects_too_many_windows_before_merge(self) -> None:
        raw = {"blocked_windows": [{"start": f"{i:02d}:00", "end": f"{i:02d}:30"} for i in range(6)]}
        with pytest.raises(ValueError, match="At most 5"):
            validate_and_normalize_schedule_restriction(raw)

    @parameterized.expand(
        [
            ("12:00:00",),
            ("not_a_time",),
        ]
    )
    def test_rejects_malformed_times(self, bad_time: str) -> None:
        raw = {"blocked_windows": [{"start": bad_time, "end": "13:00"}]}
        with pytest.raises(ValueError):
            validate_and_normalize_schedule_restriction(raw)

    def test_rejects_equal_start_and_end(self) -> None:
        raw = {"blocked_windows": [{"start": "10:00", "end": "10:00"}]}
        with pytest.raises(ValueError, match="differ"):
            validate_and_normalize_schedule_restriction(raw)

    def test_rejects_same_day_window_shorter_than_30_minutes(self) -> None:
        raw = {"blocked_windows": [{"start": "10:00", "end": "10:29"}]}
        with pytest.raises(ValueError, match="at least 30 minutes"):
            validate_and_normalize_schedule_restriction(raw)

    def test_accepts_same_day_window_exactly_30_minutes(self) -> None:
        raw = {"blocked_windows": [{"start": "10:00", "end": "10:30"}]}
        assert validate_and_normalize_schedule_restriction(raw) == {
            "blocked_windows": [{"start": "10:00", "end": "10:30"}],
        }

    def test_rejects_overnight_window_shorter_than_30_minutes(self) -> None:
        raw = {"blocked_windows": [{"start": "23:50", "end": "00:09"}]}
        with pytest.raises(ValueError, match="at least 30 minutes"):
            validate_and_normalize_schedule_restriction(raw)

    def test_accepts_overnight_window_exactly_30_minutes(self) -> None:
        raw = {"blocked_windows": [{"start": "23:40", "end": "00:10"}]}
        assert validate_and_normalize_schedule_restriction(raw) == {
            "blocked_windows": [{"start": "23:40", "end": "00:10"}],
        }

    def test_evening_until_midnight_encodes_as_end_00_00(self) -> None:
        raw = {"blocked_windows": [{"start": "19:00", "end": "00:00"}]}
        out = validate_and_normalize_schedule_restriction(raw)
        assert out == {"blocked_windows": [{"start": "19:00", "end": "00:00"}]}


class TestIsUtcDatetimeBlockedAndNextUnblocked:
    def _alert(self, tz: str, restriction: dict[str, Any] | None) -> MagicMock:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "test-id"
        alert.team = MagicMock()
        alert.team.timezone = tz
        alert.schedule_restriction = restriction
        return alert

    @parameterized.expand(
        [
            ("2024-06-01T10:30:00+00:00", True),
            ("2024-06-01T10:00:00+00:00", True),
            ("2024-06-01T12:00:00+00:00", False),
            ("2024-06-01T09:59:00+00:00", False),
        ]
    )
    def test_same_day_window_half_open_utc_team(self, iso: str, blocked: bool) -> None:
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        dt = datetime.fromisoformat(iso)
        assert is_utc_datetime_blocked(alert, dt) is blocked

    def test_overnight_block_covers_local_night_utc_team(self) -> None:
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
        )
        assert is_utc_datetime_blocked(alert, datetime(2024, 6, 1, 23, 0, tzinfo=UTC)) is True
        assert is_utc_datetime_blocked(alert, datetime(2024, 6, 1, 3, 0, tzinfo=UTC)) is True
        assert is_utc_datetime_blocked(alert, datetime(2024, 6, 1, 7, 0, tzinfo=UTC)) is False
        assert is_utc_datetime_blocked(alert, datetime(2024, 6, 1, 21, 59, tzinfo=UTC)) is False

    def test_next_unblocked_advances_to_end_of_window(self) -> None:
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        fro = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
        nxt = next_unblocked_utc(alert, fro)
        assert nxt == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

    def test_next_unblocked_retries_next_day_when_minute_walk_hits_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(schedule_restriction_module, "_MAX_UNBLOCK_STEPS", 5)
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        fro = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
        nxt = next_unblocked_utc(alert, fro)
        # First walk stops early; retry from next day also hits cap with same limit; last resort +1 day from bump.
        assert nxt == datetime(2024, 6, 3, 11, 0, tzinfo=UTC)

    def test_next_unblocked_second_cap_returns_day_after_bump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(schedule_restriction_module, "_MAX_UNBLOCK_STEPS", 5)
        alert = self._alert(
            "UTC",
            {"blocked_windows": [{"start": "10:00", "end": "12:00"}]},
        )
        fro = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
        nxt = schedule_restriction_module._next_unblocked_utc(alert, fro, recursion_depth=1)
        assert nxt == datetime(2024, 6, 2, 11, 0, tzinfo=UTC)
