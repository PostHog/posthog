from datetime import UTC, datetime

from parameterized import parameterized

from products.alerts.backend.calendar import (
    CalendarInterval,
    is_weekend,
    next_calendar_check_time,
    parse_blocked_windows_tuples,
    scan_next_unblocked_utc,
    validate_and_normalize_schedule_restriction,
)

# Wednesday 2026-03-18 12:00 UTC
NOW = datetime(2026, 3, 18, 12, 0, tzinfo=UTC)
PREV_CHECK = datetime(2026, 3, 18, 11, 47, tzinfo=UTC)


class TestNextCalendarCheckTime:
    @parameterized.expand(
        [
            # Sub-daily intervals advance from the prior next_check_at, preserving per-alert spread
            ("real_time_from_prev", CalendarInterval.REAL_TIME, PREV_CHECK, datetime(2026, 3, 18, 11, 49, tzinfo=UTC)),
            ("real_time_first_check", CalendarInterval.REAL_TIME, None, datetime(2026, 3, 18, 12, 2, tzinfo=UTC)),
            (
                "15min_from_prev",
                CalendarInterval.EVERY_15_MINUTES,
                PREV_CHECK,
                datetime(2026, 3, 18, 12, 2, tzinfo=UTC),
            ),
            ("hourly_from_prev", CalendarInterval.HOURLY, PREV_CHECK, datetime(2026, 3, 18, 12, 47, tzinfo=UTC)),
        ]
    )
    def test_sub_daily_advances_from_previous(
        self, _name: str, interval: CalendarInterval, next_check_at: datetime | None, expected: datetime
    ) -> None:
        result = next_calendar_check_time(interval, now=NOW, tz_name="UTC", next_check_at=next_check_at)
        assert result == expected

    @parameterized.expand(
        [
            # Daily anchors to ~1am local tomorrow; minute preserved for spread. US/Pacific is UTC-7 on this date.
            ("daily_pacific", CalendarInterval.DAILY, "US/Pacific", (2026, 3, 19, 8, 0)),
            # Weekly anchors to ~3am next Monday local (Mon 2026-03-23), 3am PDT = 10:00 UTC
            ("weekly_pacific", CalendarInterval.WEEKLY, "US/Pacific", (2026, 3, 23, 10, 0)),
            # Monthly anchors to ~4am on the 1st of next month, 4am PDT = 11:00 UTC
            ("monthly_pacific", CalendarInterval.MONTHLY, "US/Pacific", (2026, 4, 1, 11, 0)),
        ]
    )
    def test_calendar_anchors_in_team_timezone(
        self, _name: str, interval: CalendarInterval, tz_name: str, expected_utc: tuple
    ) -> None:
        result = next_calendar_check_time(interval, now=NOW, tz_name=tz_name, next_check_at=PREV_CHECK)
        assert (result.year, result.month, result.day, result.hour, result.minute) == expected_utc
        assert result.tzinfo is not None

    def test_daily_across_dst_spring_forward(self) -> None:
        # US spring-forward was 2026-03-08: local 1am tomorrow maps PST(-8) -> PDT(-7),
        # so the UTC anchor shifts from 09:00 to 08:00 across the transition.
        before = next_calendar_check_time(
            CalendarInterval.DAILY,
            now=datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
            tz_name="US/Pacific",
            next_check_at=None,
        )
        after = next_calendar_check_time(
            CalendarInterval.DAILY,
            now=datetime(2026, 3, 8, 12, 0, tzinfo=UTC),
            tz_name="US/Pacific",
            next_check_at=None,
        )
        assert before.hour == 9
        assert after.hour == 8


class TestIsWeekend:
    @parameterized.expand(
        [
            # Friday 23:00 UTC is already Saturday 08:00 in Tokyo
            ("tokyo_saturday", datetime(2026, 3, 20, 23, 0, tzinfo=UTC), "Asia/Tokyo", True),
            ("utc_friday", datetime(2026, 3, 20, 23, 0, tzinfo=UTC), "UTC", False),
            # Sunday 05:00 UTC is still Saturday 22:00 in Pacific
            ("pacific_saturday", datetime(2026, 3, 22, 5, 0, tzinfo=UTC), "US/Pacific", True),
            ("monday_utc", datetime(2026, 3, 23, 9, 0, tzinfo=UTC), "UTC", False),
        ]
    )
    def test_weekend_is_local(self, _name: str, now: datetime, tz_name: str, expected: bool) -> None:
        assert is_weekend(now, tz_name) == expected


class TestScanNextUnblockedUtc:
    def _windows(self, *pairs: tuple[str, str]):
        raw = {"blocked_windows": [{"start": s, "end": e} for s, e in pairs]}
        return parse_blocked_windows_tuples(validate_and_normalize_schedule_restriction(raw))

    @parameterized.expand(
        [
            # Candidate inside a same-day window snaps to the window end (half-open)
            ("inside_window", ("09:00", "17:00"), datetime(2026, 3, 18, 12, 30, tzinfo=UTC), "UTC", (17, 0)),
            # Candidate outside any window is returned unchanged (minute precision)
            ("outside_window", ("09:00", "17:00"), datetime(2026, 3, 18, 18, 15, tzinfo=UTC), "UTC", (18, 15)),
            # Overnight window (22:00-06:00): a 23:00 candidate snaps to 06:00 next day
            ("overnight_window", ("22:00", "06:00"), datetime(2026, 3, 18, 23, 0, tzinfo=UTC), "UTC", (6, 0)),
        ]
    )
    def test_snapping(
        self, _name: str, window: tuple[str, str], candidate: datetime, tz_name: str, expected_hm: tuple
    ) -> None:
        result = scan_next_unblocked_utc(candidate, tz_name, self._windows(window))
        assert result is not None
        assert (result.hour, result.minute) == expected_hm

    def test_window_is_evaluated_in_local_time(self) -> None:
        # Blocked 09:00-17:00 in Pacific (PDT, UTC-7). 12:00 UTC = 05:00 local -> not blocked.
        windows = self._windows(("09:00", "17:00"))
        result = scan_next_unblocked_utc(datetime(2026, 3, 18, 12, 0, tzinfo=UTC), "US/Pacific", windows)
        assert result == datetime(2026, 3, 18, 12, 0, tzinfo=UTC)
        # 18:00 UTC = 11:00 local -> blocked until 17:00 local = 00:00 UTC next day.
        result = scan_next_unblocked_utc(datetime(2026, 3, 18, 18, 0, tzinfo=UTC), "US/Pacific", windows)
        assert result is not None
        assert result == datetime(2026, 3, 19, 0, 0, tzinfo=UTC)

    def test_no_windows_returns_candidate(self) -> None:
        candidate = datetime(2026, 3, 18, 12, 30, 45, 123456, tzinfo=UTC)
        assert scan_next_unblocked_utc(candidate, "UTC", None) == candidate.replace(microsecond=0)

    def test_full_day_coverage_is_rejected_at_validation(self) -> None:
        try:
            validate_and_normalize_schedule_restriction(
                {"blocked_windows": [{"start": "00:00", "end": "12:00"}, {"start": "12:00", "end": "00:00"}]}
            )
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
