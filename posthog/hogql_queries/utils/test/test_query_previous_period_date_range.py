from datetime import timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from dateutil import parser
from parameterized import parameterized

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

    @parameterized.expand(
        [
            ("earliest event at midnight", "2021-07-06T00:00:00Z", "2021-05-16T00:00:00Z"),
            ("earliest event mid-day", "2021-07-06T12:34:00Z", "2021-05-17T01:08:00Z"),
        ]
    )
    def test_previous_period_for_all_time_ends_before_the_earliest_event(
        self, _name: str, earliest_timestamp: str, expected_date_from: str
    ):
        # The previous period has to stop before the first event, or the comparison counts part of the
        # first day twice and reports it as the previous period's total. Two ways that happened: the
        # "-7d is really 8 days" correction in get_compare_period_dates shifted the whole period a day
        # later, and its end takes date_to's time of day, which for a mid-day first event lands after
        # the current period already started.
        now = parser.isoparse("2021-08-25T12:34:00.000Z")
        date_range = DateRange(date_from="all")
        query_date_range = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            earliest_timestamp_fallback=parser.isoparse(earliest_timestamp),
        )
        self.assertEqual(query_date_range.date_to(), parser.isoparse(earliest_timestamp) - timedelta(microseconds=1))
        self.assertEqual(query_date_range.date_from(), parser.isoparse(expected_date_from))

    @parameterized.expand(
        [
            # A day-anchored range at hour granularity used to size the previous period from the
            # elapsed part of today (ending 12:59), truncating it. It now spans the full previous
            # day, matching how day/week/month intervals already behave.
            ("today_hour", "dStart", IntervalType.HOUR, "2021-08-24T00:00:00Z", "2021-08-24T23:59:59.999999Z"),
            ("today_minute", "dStart", IntervalType.MINUTE, "2021-08-24T00:00:00.000001Z", "2021-08-25T00:00:00Z"),
            ("last_7d_hour", "-7d", IntervalType.HOUR, "2021-08-10T00:00:00Z", "2021-08-17T23:59:59.999999Z"),
            # A rolling sub-day window is unchanged: its previous period is just the window before it.
            ("last_24h_hour", "-24h", IntervalType.HOUR, "2021-08-23T12:00:00Z", "2021-08-24T12:59:59.999999Z"),
        ]
    )
    def test_previous_period_hourly_range_sizing(
        self, _name: str, date_from: str, interval: IntervalType, expected_from: str, expected_to: str
    ):
        now = parser.isoparse("2021-08-25T12:34:00.000Z")
        query_date_range = QueryPreviousPeriodDateRange(
            team=self.team, date_range=DateRange(date_from=date_from), interval=interval, now=now
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse(expected_from))
        self.assertEqual(query_date_range.date_to(), parser.isoparse(expected_to))

    @parameterized.expand(
        [
            # "This week/month/quarter/year" run to now, so the current period is partial. The previous
            # period is the full prior calendar unit (weekday/day-of-month aligned, complete), matching
            # how day-anchored hour/minute ranges already behave — not the trailing slice of it.
            ("this_week", "2021-08-25T12:34:00Z", "wStart", "2021-08-15T00:00:00Z", "2021-08-21T23:59:59.999999Z"),
            ("this_month", "2021-08-25T12:34:00Z", "mStart", "2021-07-01T00:00:00Z", "2021-07-31T23:59:59.999999Z"),
            # A shorter previous month must still come back whole: diff-in-days sizing can't express this.
            (
                "this_month_february",
                "2021-03-15T12:34:00Z",
                "mStart",
                "2021-02-01T00:00:00Z",
                "2021-02-28T23:59:59.999999Z",
            ),
            ("this_quarter", "2021-08-25T12:34:00Z", "qStart", "2021-04-01T00:00:00Z", "2021-06-30T23:59:59.999999Z"),
            ("this_year", "2021-08-25T12:34:00Z", "yStart", "2020-01-01T00:00:00Z", "2020-12-31T23:59:59.999999Z"),
        ]
    )
    def test_previous_period_for_calendar_anchored_range_is_full_prior_unit(
        self, _name: str, now: str, date_from: str, expected_from: str, expected_to: str
    ):
        query_date_range = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=DateRange(date_from=date_from),
            interval=IntervalType.DAY,
            now=parser.isoparse(now),
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse(expected_from))
        self.assertEqual(query_date_range.date_to(), parser.isoparse(expected_to))

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
