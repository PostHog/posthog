from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from dateutil import parser

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange


class TestQueryCompareToDateRange(APIBaseTest):
    def test_zero(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryCompareToDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now, compare_to="-0d"
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25T23:59:59.999999Z"))

    def test_minus_one_month(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryCompareToDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now, compare_to="-1m"
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-07-23T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-07-25T23:59:59.999999Z"))

    def test_minus_one_year(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryCompareToDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now, compare_to="-1y"
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2020-08-23T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2020-08-25T23:59:59.999999Z"))

    def test_feb(self):
        now = parser.isoparse("2021-03-31T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryCompareToDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now, compare_to="-1m"
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-02-28T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-03-02T23:59:59.999999Z"))

    # Same as above but with human friendly comparison periods, should use week instead of month/year
    def test_minus_one_month_human_friendly(self):
        self.team.human_friendly_comparison_periods = True

        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryCompareToDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            compare_to="-1m",
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-07-26T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-07-28T23:59:59.999999Z"))

        # Human friendly comparison periods guarantee that the end of the week is same day
        self.assertEqual(query_date_range.date_to().isoweekday(), now.isoweekday())

    def test_explicit_timezone_info_overrides_team_timezone(self):
        # The compare-period parsing used to read directly from `self._team.timezone_info`,
        # so a `timezone_info=UTC` override on the constructor was silently ignored.
        # With the fix it should resolve `compare_to` in the explicitly-passed timezone.
        self.team.timezone = "US/Pacific"
        self.team.save()

        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        with_override = QueryCompareToDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            compare_to="-1d",
            timezone_info=ZoneInfo("UTC"),
        )
        without_override = QueryCompareToDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            compare_to="-1d",
        )
        # With the override the compare period anchors to UTC; without it, to US/Pacific.
        # The two must produce different instants — otherwise the override has no effect.
        self.assertNotEqual(with_override.date_from(), without_override.date_from())
        # And the override produces the same result as a UTC-team baseline would.
        self.team.timezone = "UTC"
        self.team.save()
        utc_baseline = QueryCompareToDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            compare_to="-1d",
        )
        self.assertEqual(with_override.date_from(), utc_baseline.date_from())
        self.assertEqual(with_override.date_to(), utc_baseline.date_to())

    def test_minus_one_year_human_friendly(self):
        self.team.human_friendly_comparison_periods = True

        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryCompareToDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            compare_to="-1y",
        )
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2020-08-24T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2020-08-26T23:59:59.999999Z"))

        # Human friendly comparison periods guarantee that the end of the week is same day
        self.assertEqual(query_date_range.date_to().isoweekday(), now.isoweekday())
