from datetime import timedelta

from dateutil import parser

from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange, QueryDateRangeWithIntervals
from posthog.models.team import WeekStartDay
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


class TestQueryDateRangeWithIntervals(APIBaseTest):
    def setUp(self):
        self.now = parser.isoparse("2021-08-25T00:00:00.000Z")
        self.total_intervals = 5

    def test_constructor_initialization(self):
        query = QueryDateRangeWithIntervals(None, self.total_intervals, self.team, IntervalType.day, self.now)
        self.assertEqual(query.total_intervals, self.total_intervals)

    def test_determine_time_delta_valid(self):
        delta = QueryDateRangeWithIntervals.determine_time_delta(5, "day")
        self.assertEqual(delta, timedelta(days=5))

    def test_determine_time_delta_invalid_period(self):
        with self.assertRaises(ValueError):
            QueryDateRangeWithIntervals.determine_time_delta(5, "decade")

    def test_date_from_day_interval(self):
        query = QueryDateRangeWithIntervals(None, 2, self.team, IntervalType.day, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-24T00:00:00Z"))

    def test_date_from_hour_interval(self):
        query = QueryDateRangeWithIntervals(None, 48, self.team, IntervalType.hour, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-23T01:00:00Z"))

    def test_date_from_week_interval_starting_monday(self):
        self.team.week_start_day = WeekStartDay.MONDAY
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.week, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))

    def test_date_from_week_interval_starting_sunday(self):
        self.team.week_start_day = WeekStartDay.SUNDAY
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.week, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-22T00:00:00Z"))

    def test_date_to_day_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.day, self.now)
        self.assertEqual(query.date_to(), parser.isoparse("2021-08-26T00:00:00Z"))

    def test_date_to_hour_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.hour, self.now)
        self.assertEqual(query.date_to(), parser.isoparse("2021-08-25T01:00:00Z"))

    def test_get_start_of_interval_hogql_day_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.day, self.now)
        expected_expr = ast.Call(name="toStartOfDay", args=[ast.Constant(value=query.date_from())])
        self.assertEqual(query.get_start_of_interval_hogql(), expected_expr)

    def test_get_start_of_interval_hogql_hour_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.hour, self.now)
        expected_expr = ast.Call(name="toStartOfHour", args=[ast.Constant(value=query.date_from())])
        self.assertEqual(query.get_start_of_interval_hogql(), expected_expr)

    def test_get_start_of_interval_hogql_week_interval(self):
        self.team.week_start_day = WeekStartDay.MONDAY
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.week, self.now)
        week_mode = WeekStartDay(self.team.week_start_day or 0).clickhouse_mode
        expected_expr = ast.Call(
            name="toStartOfWeek", args=[ast.Constant(value=query.date_from()), ast.Constant(value=int(week_mode))]
        )
        self.assertEqual(query.get_start_of_interval_hogql(), expected_expr)

    def test_get_start_of_interval_hogql_with_source(self):
        source_expr = ast.Constant(value="2021-08-25T00:00:00.000Z")
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.day, self.now)
        expected_expr = ast.Call(name="toStartOfDay", args=[source_expr])
        self.assertEqual(query.get_start_of_interval_hogql(source=source_expr), expected_expr)
