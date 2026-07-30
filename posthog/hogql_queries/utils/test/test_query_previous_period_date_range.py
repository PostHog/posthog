from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from dateutil import parser

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange


class TestQueryPreviousPeriodDateRange(APIBaseTest):
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

    def test_previous_period_with_exclude_incomplete_periods_stays_aligned(self):
        # The "-7d is really 8 days" kludge in get_compare_period_dates adds a day to counteract
        # the ongoing day, but a clipped range no longer includes it: current period is exactly
        # Wed Aug 18 - Tue Aug 24, so the previous period must be Wed Aug 11 - Tue Aug 17
        # (weekday-aligned, non-overlapping), not Aug 12 - Aug 18.
        now = parser.isoparse("2021-08-25T10:00:00.000Z")
        date_range = DateRange(date_from="-7d", excludeIncompletePeriods=True)
        query_date_range = QueryPreviousPeriodDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-11T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-17T23:59:59.999999Z"))

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
