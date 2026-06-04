from datetime import timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from dateutil import parser
from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange


class TestQueryPreviousPeriodDateRange(APIBaseTest):
    def _previous_period(
        self, date_from: str, now_iso: str, date_to: str | None = None
    ) -> QueryPreviousPeriodDateRange:
        return QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=DateRange(date_from=date_from, date_to=date_to),
            interval=IntervalType.DAY,
            now=parser.isoparse(now_iso),
        )

    def test_previous_period(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryPreviousPeriodDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now
        )
        # Current period [2021-08-23T00:00, 2021-08-25T23:59:59] is ~3 days inclusive.
        # The previous period shifts back by that full span.
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-20T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-22T23:59:59.999999Z"))

    def test_explicit_timezone_info_overrides_team_timezone(self):
        # The previous-period delta parsing used to read directly from
        # `self._team.timezone_info`, so a `timezone_info=UTC` override on the constructor
        # was silently ignored.
        #
        # The bug surfaces in `date_from_str` / `date_to_str`, not in the datetime
        # objects themselves: both point to the same UTC instant but display in
        # different timezones. `format_date` strips the tz suffix via
        # `strftime("%Y-%m-%d %H:%M:%S")`, so the formatted string carries the
        # team-tz wall clock under the bug and the UTC wall clock with the fix.
        # That string is what flows into ClickHouse, so we assert against it.
        #
        # `date_from="-2d"` is day-based, so the midnight-of-day anchor differs between
        # US/Pacific (08-24 00:00 PDT = 08-24 07:00 UTC) and UTC (08-24 00:00 UTC).
        self.team.timezone = "US/Pacific"
        self.team.save()

        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-2d")

        with_override = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            timezone_info=ZoneInfo("UTC"),
        )
        without_override = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
        )
        # The override must change the formatted output — otherwise the test wouldn't
        # catch a regression of the fix.
        self.assertNotEqual(with_override.date_from_str, without_override.date_from_str)

        # Same setup with team on UTC and no override — should match the override result.
        self.team.timezone = "UTC"
        self.team.save()
        utc_baseline = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
        )
        self.assertEqual(with_override.date_from_str, utc_baseline.date_from_str)
        self.assertEqual(with_override.date_to_str, utc_baseline.date_to_str)

    @parameterized.expand(
        [
            # A "to date" preset is a partial window; the previous period is the same window one
            # calendar unit earlier (e.g. this month Jun 1–3 → May 1–3), not the trailing span.
            ("this_month", "mStart", "2026-05-01T00:00:00Z", "2026-05-03T23:59:59.999999Z"),
            ("today", "dStart", "2026-06-02T00:00:00Z", "2026-06-02T23:59:59.999999Z"),
            ("year_to_date", "yStart", "2025-01-01T00:00:00Z", "2025-06-03T23:59:59.999999Z"),
        ]
    )
    def test_to_date_preset_aligns_to_previous_calendar_unit(
        self, _name: str, date_from: str, expected_from: str, expected_to: str
    ):
        previous = self._previous_period(date_from, "2026-06-03T14:00:00Z")
        self.assertEqual(previous.date_from(), parser.isoparse(expected_from))
        self.assertEqual(previous.date_to(), parser.isoparse(expected_to))

    def test_this_week_aligns_to_previous_week(self):
        # Robust to the team's week-start config: assert the window is shifted back exactly one
        # week and keeps the same (partial) duration.
        date_range = DateRange(date_from="wStart")
        now = parser.isoparse("2026-06-03T14:00:00Z")
        previous = QueryPreviousPeriodDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now
        )
        current = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(previous.date_from(), current.date_from() - timedelta(weeks=1))
        self.assertEqual(previous.date_to() - previous.date_from(), current.date_to() - current.date_from())

    @parameterized.expand(
        [
            ("today", "dStart", relativedelta(days=1)),
            ("this_week", "wStart", relativedelta(weeks=1)),
            ("this_month", "mStart", relativedelta(months=1)),
            ("year_to_date", "yStart", relativedelta(years=1)),
        ]
    )
    def test_to_date_presets_are_detected(self, _name: str, date_from: str, expected: relativedelta):
        self.assertEqual(self._previous_period(date_from, "2026-06-03T14:00:00Z").to_date_preset_shift(), expected)

    @parameterized.expand(
        [
            ("last_7_days", "-7d"),
            ("last_14_days", "-14d"),
            ("last_30_days", "-30d"),
            ("last_hour", "-1h"),
            ("quarter_start_not_a_ui_preset", "qStart"),
            ("hour_start_not_a_ui_preset", "hStart"),
            ("yesterday_with_number", "-1dStart"),
            ("all_time", "all"),
        ]
    )
    def test_fixed_windows_are_not_aligned(self, _name: str, date_from: str):
        # Fixed-length and numbered ranges keep the default "shift back by window length" behavior.
        self.assertIsNone(self._previous_period(date_from, "2026-06-03T14:00:00Z").to_date_preset_shift())

    def test_explicit_date_to_disables_alignment(self):
        # A "to date" preset with an explicit end is no longer an open-ended partial period.
        previous = self._previous_period("mStart", "2026-06-03T14:00:00Z", date_to="2026-06-02T00:00:00Z")
        self.assertIsNone(previous.to_date_preset_shift())
