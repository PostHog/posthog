from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.services.sla import compute_sla_deadline, is_calendar_hours

ALL_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS_ONLY = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def _dt(year, month, day, hour=0, minute=0, second=0, microsecond=0, tz=UTC):
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=tz)


class TestIsCalendarHours(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, True),
            ("empty_dict", {}, True),
            ("all_days_any_time", {"days": ALL_DAYS, "time": "any", "timezone": "UTC"}, True),
            ("all_days_custom_time", {"days": ALL_DAYS, "time": ["09:00", "17:00"], "timezone": "UTC"}, False),
            ("weekdays_any_time", {"days": WEEKDAYS_ONLY, "time": "any", "timezone": "UTC"}, False),
            # 7 unique garbage day names should NOT be treated as calendar hours
            ("seven_garbage_names", {"days": ["a", "b", "c", "d", "e", "f", "g"], "time": "any"}, False),
            # Strict subset count that happens to == 7 after dedup — must match WEEKDAYS exactly
            ("weekdays_plus_dupes", {"days": ["monday"] * 7, "time": "any"}, False),
            # days is a string — treat as not calendar (avoids set('monday') bug)
            ("days_as_string", {"days": "monday", "time": "any"}, False),
            # Extra valid day (len==8) still fine but not calendar (we require == 7)
            ("extra_day", {"days": [*ALL_DAYS, "monday"], "time": "any"}, True),
            # Explicit dedup check — 7 real weekdays in different order
            ("all_days_reordered", {"days": list(reversed(ALL_DAYS)), "time": "any"}, True),
        ]
    )
    def test_is_calendar_hours(self, _name, config, expected):
        self.assertEqual(is_calendar_hours(config), expected)


class TestCalendarHoursFastPath(SimpleTestCase):
    """No business hours config => plain now + timedelta."""

    @parameterized.expand(
        [
            ("no_config", None),
            ("empty_dict", {}),
            ("all_days_any_time_utc", {"days": ALL_DAYS, "time": "any", "timezone": "UTC"}),
            ("all_days_any_time_ny", {"days": ALL_DAYS, "time": "any", "timezone": "America/New_York"}),
        ]
    )
    def test_calendar_hours(self, _name, config):
        now = _dt(2026, 1, 5, 10, 0)  # Monday 10:00 UTC
        deadline = compute_sla_deadline(now=now, amount=10, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 20, 0))

    def test_calendar_days_unit(self):
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=2, unit="day", business_hours=None)
        self.assertEqual(deadline, _dt(2026, 1, 7, 10, 0))

    def test_calendar_minutes_unit(self):
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=90, unit="minute", business_hours=None)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 30))

    def test_fractional_calendar_hours(self):
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=1.5, unit="hour", business_hours=None)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 30))


class TestBusinessHoursWindow(SimpleTestCase):
    """Weekdays 09:00-17:00 UTC — 8h window."""

    def setUp(self):
        self.config = {
            "days": WEEKDAYS_ONLY,
            "time": ["09:00", "17:00"],
            "timezone": "UTC",
        }

    def test_plan_example_ten_hours_from_thursday_16(self):
        """SLA 10h, 9-5 Mon-Fri, triggered Thu 16:00 local.

        - Thu 16:00 -> 17:00 consumes 1h (9h remaining)
        - Fri 09:00 -> 17:00 consumes 8h (1h remaining)
        - Mon 09:00 + 1h = Mon 10:00 local => deadline.
        """
        now = _dt(2026, 1, 8, 16, 0)  # Thursday 2026-01-08 16:00 UTC
        deadline = compute_sla_deadline(now=now, amount=10, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 12, 10, 0))  # Monday 10:00

    def test_inside_window_fits_same_day(self):
        now = _dt(2026, 1, 5, 10, 0)  # Mon 10:00
        deadline = compute_sla_deadline(now=now, amount=3, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 13, 0))  # Mon 13:00

    def test_before_window_starts_at_open(self):
        now = _dt(2026, 1, 5, 6, 0)  # Mon 06:00
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 10, 0))  # Mon 10:00

    def test_after_window_rolls_to_next_day(self):
        now = _dt(2026, 1, 5, 18, 0)  # Mon 18:00 (past close)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 6, 10, 0))  # Tue 10:00

    def test_at_window_close_rolls_to_next_day(self):
        """Triggered at exactly 17:00 — window is [09:00, 17:00) so we roll."""
        now = _dt(2026, 1, 5, 17, 0)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 6, 10, 0))

    def test_at_window_open_starts_immediately(self):
        now = _dt(2026, 1, 5, 9, 0)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 10, 0))

    def test_remaining_exactly_equals_available(self):
        """Consume exactly to window close."""
        now = _dt(2026, 1, 5, 9, 0)
        deadline = compute_sla_deadline(now=now, amount=8, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 17, 0))

    def test_triggered_on_weekend_rolls_to_monday(self):
        now = _dt(2026, 1, 3, 12, 0)  # Saturday
        deadline = compute_sla_deadline(now=now, amount=2, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 0))  # Mon 11:00

    def test_friday_late_skips_weekend(self):
        """Fri 16:00 + 3h business hours.

        - Fri 16-17 consumes 1h (2h remaining)
        - Sat/Sun skipped
        - Mon 09:00 + 2h = Mon 11:00
        """
        now = _dt(2026, 1, 9, 16, 0)  # Friday 16:00
        deadline = compute_sla_deadline(now=now, amount=3, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 12, 11, 0))

    def test_ten_day_sla_crosses_multiple_weeks(self):
        now = _dt(2026, 1, 5, 9, 0)  # Mon 09:00
        # 10 business days * 8h/day = 80h; 8h/day Mon-Fri -> 2 full weeks
        deadline = compute_sla_deadline(now=now, amount=10, unit="day", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 16, 17, 0))  # Fri two weeks later, end-of-day

    def test_day_unit_with_custom_window(self):
        """1 day == one window-length (8h for 09:00-17:00)."""
        now = _dt(2026, 1, 5, 9, 0)  # Mon 09:00
        deadline = compute_sla_deadline(now=now, amount=1, unit="day", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 17, 0))  # Mon 17:00

    def test_day_unit_rolls_across_working_days(self):
        """2 days = 16h. Mon 13:00 + 16h business = Tue 13:00 (consume 4h Mon, 8h Tue... wait)."""
        # Mon 13:00 → 17:00 = 4h. Tue 09:00 → 17:00 = 8h. Wed 09:00 → start + 4h = Wed 13:00.
        now = _dt(2026, 1, 5, 13, 0)
        deadline = compute_sla_deadline(now=now, amount=2, unit="day", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 7, 13, 0))

    def test_day_unit_any_time_is_24h(self):
        config = {"days": WEEKDAYS_ONLY, "time": "any", "timezone": "UTC"}
        now = _dt(2026, 1, 5, 10, 0)  # Mon 10:00
        # 1 "day" == 24h wall-clock. On a working day it consumes the rest of
        # Monday (14h) and then 10h of Tuesday -> Tue 10:00.
        deadline = compute_sla_deadline(now=now, amount=1, unit="day", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 1, 6, 10, 0))

    def test_minutes_unit(self):
        now = _dt(2026, 1, 5, 9, 0)
        deadline = compute_sla_deadline(now=now, amount=45, unit="minute", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 9, 45))

    def test_sub_minute_amount(self):
        """0.5 minutes = 30 seconds."""
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=0.5, unit="minute", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 10, 0, 30))

    def test_fractional_hour_amount(self):
        """1.5h = 90 minutes."""
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=1.5, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 30))

    def test_preserves_subsecond_precision_when_inside_window(self):
        now = _dt(2026, 1, 5, 10, 0, 30, 250000)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=self.config)
        # 10:00:30.25 + 1h = 11:00:30.25
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 0, 30, 250000))

    def test_single_working_day_only_monday(self):
        """With only monday configured, Tue 10:00 + 1h rolls to next Mon 10:00."""
        config = {"days": ["monday"], "time": ["09:00", "17:00"], "timezone": "UTC"}
        now = _dt(2026, 1, 6, 10, 0)  # Tuesday
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 1, 12, 10, 0))  # next Monday

    def test_all_days_plus_specific_time_not_calendar(self):
        """ALL 7 days + 09:00-17:00 is legit business hours, not the fast path."""
        config = {"days": ALL_DAYS, "time": ["09:00", "17:00"], "timezone": "UTC"}
        now = _dt(2026, 1, 5, 16, 0)  # Mon 16:00, 1h left in window
        deadline = compute_sla_deadline(now=now, amount=3, unit="hour", business_hours=config)
        # Mon 16-17 = 1h. Tue 09-11 = 2h. → Tue 11:00.
        self.assertEqual(deadline, _dt(2026, 1, 6, 11, 0))

    def test_near_full_day_window(self):
        """00:00-23:59 window, 1h amount."""
        config = {"days": ALL_DAYS, "time": ["00:00", "23:59"], "timezone": "UTC"}
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 0))

    def test_duplicates_in_days_list(self):
        """Duplicate day names are deduped."""
        config = {
            "days": ["monday", "monday", "friday", "friday"],
            "time": ["09:00", "17:00"],
            "timezone": "UTC",
        }
        now = _dt(2026, 1, 5, 10, 0)  # Monday
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 0))

    def test_default_timezone_is_utc(self):
        """Omitted timezone falls back to UTC."""
        config = {"days": WEEKDAYS_ONLY, "time": ["09:00", "17:00"]}
        now = _dt(2026, 1, 5, 10, 0)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 1, 5, 11, 0))

    def test_amount_larger_than_single_window(self):
        """20h with 8h window spans multiple days."""
        now = _dt(2026, 1, 5, 9, 0)  # Mon 09:00
        # 20h = 8h Mon + 8h Tue + 4h of Wed (09-13) → Wed 13:00
        deadline = compute_sla_deadline(now=now, amount=20, unit="hour", business_hours=self.config)
        self.assertEqual(deadline, _dt(2026, 1, 7, 13, 0))


class TestTimezoneHandling(SimpleTestCase):
    def test_timezone_la_trigger_utc(self):
        """Window in America/Los_Angeles (UTC-8 in January), trigger expressed in UTC."""
        config = {
            "days": WEEKDAYS_ONLY,
            "time": ["09:00", "17:00"],
            "timezone": "America/Los_Angeles",
        }
        # 2026-01-05 18:00 UTC == 2026-01-05 10:00 LA (Monday, inside window).
        now = _dt(2026, 1, 5, 18, 0)
        deadline = compute_sla_deadline(now=now, amount=2, unit="hour", business_hours=config)
        # 10:00 LA + 2h = 12:00 LA == 20:00 UTC
        self.assertEqual(deadline, _dt(2026, 1, 5, 20, 0))

    def test_timezone_tokyo_rollover(self):
        config = {
            "days": WEEKDAYS_ONLY,
            "time": ["09:00", "17:00"],
            "timezone": "Asia/Tokyo",
        }
        # 2026-01-05 08:00 UTC == 2026-01-05 17:00 Tokyo (exactly at close, past-window).
        now = _dt(2026, 1, 5, 8, 0)
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=config)
        # Should roll to Tue 10:00 Tokyo == Tue 01:00 UTC
        self.assertEqual(deadline, _dt(2026, 1, 6, 1, 0))

    def test_trigger_in_nonutc_tz(self):
        """`now` in Europe/Berlin instead of UTC — result is always UTC."""
        config = {
            "days": WEEKDAYS_ONLY,
            "time": ["09:00", "17:00"],
            "timezone": "Europe/Berlin",
        }
        berlin = ZoneInfo("Europe/Berlin")
        now = datetime(2026, 1, 5, 10, 0, tzinfo=berlin)  # Mon 10:00 Berlin = 09:00 UTC
        deadline = compute_sla_deadline(now=now, amount=1, unit="hour", business_hours=config)
        # 10:00 Berlin + 1h = 11:00 Berlin = 10:00 UTC
        self.assertEqual(deadline, _dt(2026, 1, 5, 10, 0))


class TestDstCrossing(SimpleTestCase):
    """DST transitions must preserve wall-clock duration, not UTC elapsed."""

    def test_window_after_dst_transition_day(self):
        """Spring-forward 2026-03-08 in NY. Window 09-17 on that day is still
        8h of EDT; 02:00 shift happens before open."""
        config = {
            "days": ALL_DAYS,
            "time": ["09:00", "17:00"],
            "timezone": "America/New_York",
        }
        # Saturday 2026-03-07 20:00 EST = 2026-03-08 01:00 UTC (past Sat window close).
        # Next window: Sun 2026-03-08 09:00 EDT = 13:00 UTC. + 2h = 15:00 UTC.
        now = _dt(2026, 3, 8, 1, 0)
        deadline = compute_sla_deadline(now=now, amount=2, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 3, 8, 15, 0))

    def test_fall_back_dst_still_wall_clock(self):
        """Fall-back 2026-11-01 in NY: 02:00 EDT rolls back to 01:00 EST.
        A 09-17 window on that day is still 8h of wall-clock regardless."""
        config = {
            "days": ALL_DAYS,
            "time": ["09:00", "17:00"],
            "timezone": "America/New_York",
        }
        # Sun 2026-11-01 14:00 UTC. NY after fall-back at that moment is EST (UTC-5)
        # so 14:00 UTC = 09:00 EST. + 3h = 12:00 EST = 17:00 UTC.
        now = _dt(2026, 11, 1, 14, 0)
        deadline = compute_sla_deadline(now=now, amount=3, unit="hour", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 11, 1, 17, 0))

    def test_full_day_any_time_across_dst_counts_24_wall_hours(self):
        """With time='any', "1 day" = 24 wall-clock hours, but actual UTC
        elapsed across spring-forward is 23h. Deadline should be the 24h
        wall-clock mark, not 24h of UTC elapsed."""
        config = {
            "days": ALL_DAYS,
            "time": "any",
            "timezone": "America/New_York",
        }
        # Trigger at 2026-03-07 05:00 UTC == 2026-03-07 00:00 EST.
        now = _dt(2026, 3, 7, 5, 0)
        # 1 day = 24 wall-clock hours in NY => 2026-03-08 00:00 local. That
        # local midnight is still EST (pre-shift), so = 05:00 UTC.
        deadline = compute_sla_deadline(now=now, amount=1, unit="day", business_hours=config)
        self.assertEqual(deadline, _dt(2026, 3, 8, 5, 0))


class TestRejectsBadInput(SimpleTestCase):
    @parameterized.expand(
        [
            ("naive_now", datetime(2026, 1, 5, 10, 0), 1, "hour", None),
            ("zero_amount", _dt(2026, 1, 5, 10, 0), 0, "hour", None),
            ("negative_amount", _dt(2026, 1, 5, 10, 0), -1, "hour", None),
            ("unknown_unit", _dt(2026, 1, 5, 10, 0), 1, "week", None),
            (
                "empty_days",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": [], "time": ["09:00", "17:00"], "timezone": "UTC"},
            ),
            (
                "inverted_window",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["17:00", "09:00"], "timezone": "UTC"},
            ),
            (
                "equal_window",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["09:00", "09:00"], "timezone": "UTC"},
            ),
            (
                "unknown_timezone",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["09:00", "17:00"], "timezone": "Mars/Olympus"},
            ),
            (
                "unknown_weekday_name",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ["funday"], "time": ["09:00", "17:00"], "timezone": "UTC"},
            ),
            (
                "hour_out_of_range",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["25:00", "26:00"], "timezone": "UTC"},
            ),
            (
                "minute_out_of_range",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["09:00", "09:99"], "timezone": "UTC"},
            ),
            (
                "bad_hhmm_format_three_parts",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["09:00:00", "17:00"], "timezone": "UTC"},
            ),
            (
                "bad_hhmm_non_numeric",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["nine", "five"], "timezone": "UTC"},
            ),
            (
                "time_wrong_shape",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": "weekdays", "timezone": "UTC"},
            ),
            (
                "days_as_string",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": "monday", "time": ["09:00", "17:00"], "timezone": "UTC"},
            ),
            (
                "timezone_not_string",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["09:00", "17:00"], "timezone": 5},
            ),
            (
                "time_tuple_wrong_length",
                _dt(2026, 1, 5, 10, 0),
                1,
                "hour",
                {"days": ALL_DAYS, "time": ["09:00"], "timezone": "UTC"},
            ),
        ]
    )
    def test_raises_value_error(self, _name, now, amount, unit, business_hours):
        with self.assertRaises(ValueError):
            compute_sla_deadline(now=now, amount=amount, unit=unit, business_hours=business_hours)


class TestReturnsUtc(SimpleTestCase):
    def test_returns_utc_aware(self):
        result = compute_sla_deadline(
            now=datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Europe/Berlin")),
            amount=1,
            unit="hour",
            business_hours=None,
        )
        self.assertEqual(result.utcoffset(), timedelta(0))

    def test_returns_utc_aware_business_hours_path(self):
        result = compute_sla_deadline(
            now=datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Europe/Berlin")),
            amount=1,
            unit="hour",
            business_hours={"days": WEEKDAYS_ONLY, "time": ["09:00", "17:00"], "timezone": "Europe/Berlin"},
        )
        self.assertEqual(result.utcoffset(), timedelta(0))


class TestIterationCap(SimpleTestCase):
    def test_extreme_amount_raises_value_error(self):
        """Single working day + huge amount must raise ValueError, not RuntimeError,
        so the API serializer layer returns 400 instead of 500."""
        with self.assertRaises(ValueError):
            compute_sla_deadline(
                now=_dt(2026, 1, 5, 10, 0),
                amount=3000,
                unit="hour",
                business_hours={"days": ["monday"], "time": ["09:00", "17:00"], "timezone": "UTC"},
            )
