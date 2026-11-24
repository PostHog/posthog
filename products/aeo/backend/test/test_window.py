import datetime as dt
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.aeo.backend.facade.contracts import InvalidDateRangeError
from products.aeo.backend.window import resolve_window

# 23:30 UTC on 20 October is already 21 October in Tokyo.
NOW = dt.datetime(2026, 10, 20, 23, 30, tzinfo=dt.UTC)


class TestResolveWindow(SimpleTestCase):
    @parameterized.expand(
        [
            ("default", None, None, "UTC", "2026-09-20", "2026-10-20", 31),
            ("relative_from", "-7d", None, "UTC", "2026-10-13", "2026-10-20", 8),
            ("today_only", "dStart", None, "UTC", "2026-10-20", "2026-10-20", 1),
            ("month_start", "mStart", None, "UTC", "2026-10-01", "2026-10-20", 20),
            ("iso_range", "2026-10-01", "2026-10-07", "UTC", "2026-10-01", "2026-10-07", 7),
            ("relative_to", "-14d", "-7d", "UTC", "2026-10-06", "2026-10-13", 8),
            ("future_to_reads_as_today", "2026-10-15", "2026-12-01", "UTC", "2026-10-15", "2026-10-20", 6),
            ("team_timezone_day", "-1d", None, "Asia/Tokyo", "2026-10-20", "2026-10-21", 2),
            ("longest", "-90d", None, "UTC", "2026-07-22", "2026-10-20", 91),
        ]
    )
    def test_days_are_whole_days_in_the_team_timezone(
        self,
        _name: str,
        date_from: str | None,
        date_to: str | None,
        timezone_name: str,
        expected_from: str,
        expected_to: str,
        expected_days: int,
    ) -> None:
        window = resolve_window(date_from, date_to, timezone_name=timezone_name, now=NOW)

        assert (window.window_from.isoformat(), window.window_to.isoformat(), window.days) == (
            expected_from,
            expected_to,
            expected_days,
        )
        tz = ZoneInfo(timezone_name)
        assert window.start == dt.datetime.combine(window.window_from, dt.time.min, tzinfo=tz)
        assert window.previous_start == window.start - dt.timedelta(days=expected_days)

    def test_a_range_that_ends_today_stops_at_now_and_a_past_range_at_the_end_of_its_last_day(self) -> None:
        open_range = resolve_window("-7d", None, timezone_name="UTC", now=NOW)
        past_range = resolve_window("2026-10-01", "2026-10-07", timezone_name="UTC", now=NOW)

        assert open_range.until == NOW
        assert past_range.until == dt.datetime(2026, 10, 8, tzinfo=dt.UTC)

    @parameterized.expand(
        [
            ("words", "yesterday", None, "date_from"),
            ("hours", "-24h", None, "date_from"),
            ("unreadable_to", "-7d", "soon", "date_to"),
            ("from_after_to", "2026-10-10", "2026-10-01", "date_from"),
            ("from_in_the_future", "2026-11-01", None, "date_from"),
            ("too_long", "-91d", None, "date_from"),
            ("before_earliest_day", "0001-01-01", "0001-01-01", "date_from"),
            ("relative_day_overflows", "-999999999999999999999d", None, "date_from"),
            ("iso_day_overflows", "-7d", "9999-12-31T24:00", "date_to"),
        ]
    )
    def test_rejects_a_range_it_cannot_read_or_serve(
        self, _name: str, date_from: str, date_to: str | None, field: str
    ) -> None:
        with self.assertRaises(InvalidDateRangeError) as raised:
            resolve_window(date_from, date_to, timezone_name="UTC", now=NOW)

        assert raised.exception.field == field
