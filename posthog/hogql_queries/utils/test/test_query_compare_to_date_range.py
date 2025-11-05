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
