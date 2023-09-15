from dateutil import parser

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import DateRange, IntervalType
from posthog.test.base import APIBaseTest


class TestQueryDateRange(APIBaseTest):
    def test_parsed_date(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.day, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25T23:59:59.999999Z"))

    def test_parsed_date_hour(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.hour, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(
            query_date_range.date_to(), parser.isoparse("2021-08-25T00:59:59.999999Z")
        )  # ensure last hour is included

    def test_parsed_date_middle_of_hour(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="2021-08-23 05:00:00", date_to="2021-08-26 07:00:00")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.hour, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23 05:00:00Z"))
        self.assertEqual(
            query_date_range.date_to(), parser.isoparse("2021-08-26 07:00:00Z")
        )  # ensure last hour is included

    def test_parsed_date_week(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-7d")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.week, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-18 00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25 23:59:59.999999Z"))

    def test_is_hourly(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.day, now=now)
        self.assertFalse(query_date_range.is_hourly)

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.hour, now=now)
        self.assertTrue(query_date_range.is_hourly)
