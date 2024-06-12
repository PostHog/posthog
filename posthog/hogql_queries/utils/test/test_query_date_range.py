from datetime import timedelta

from dateutil import parser

from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange, QueryDateRangeWithIntervals
from posthog.models.team import WeekStartDay
from posthog.schema import InsightDateRange, IntervalType
from posthog.test.base import APIBaseTest


class TestQueryDateRange(APIBaseTest):
    def test_parsed_date(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = InsightDateRange(date_from="-48h")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25T23:59:59.999999Z"))

    def test_parsed_date_hour(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = InsightDateRange(date_from="-48h")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.HOUR, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(
            query_date_range.date_to(), parser.isoparse("2021-08-25T00:59:59.999999Z")
        )  # ensure last hour is included

    def test_parsed_date_middle_of_hour(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = InsightDateRange(date_from="2021-08-23 05:00:00", date_to="2021-08-26 07:00:00")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.HOUR, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23 05:00:00Z"))
        self.assertEqual(
            query_date_range.date_to(), parser.isoparse("2021-08-26 07:00:00Z")
        )  # ensure last hour is included

    def test_parsed_date_week(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = InsightDateRange(date_from="-7d")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.WEEK, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-18 00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25 23:59:59.999999Z"))

    def test_all_values(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=InsightDateRange(date_from="-20h"), interval=IntervalType.DAY, now=now
            ).all_values(),
            [parser.isoparse("2021-08-24T00:00:00Z"), parser.isoparse("2021-08-25T00:00:00Z")],
        )
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=InsightDateRange(date_from="-20d"), interval=IntervalType.WEEK, now=now
            ).all_values(),
            [
                parser.isoparse("2021-08-01T00:00:00Z"),
                parser.isoparse("2021-08-08T00:00:00Z"),
                parser.isoparse("2021-08-15T00:00:00Z"),
                parser.isoparse("2021-08-22T00:00:00Z"),
            ],
        )
        self.team.week_start_day = WeekStartDay.MONDAY
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=InsightDateRange(date_from="-20d"), interval=IntervalType.WEEK, now=now
            ).all_values(),
            [
                parser.isoparse("2021-08-02T00:00:00Z"),
                parser.isoparse("2021-08-09T00:00:00Z"),
                parser.isoparse("2021-08-16T00:00:00Z"),
                parser.isoparse("2021-08-23T00:00:00Z"),
            ],
        )
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=InsightDateRange(date_from="-50d"), interval=IntervalType.MONTH, now=now
            ).all_values(),
            [parser.isoparse("2021-07-01T00:00:00Z"), parser.isoparse("2021-08-01T00:00:00Z")],
        )
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=InsightDateRange(date_from="-3h"), interval=IntervalType.HOUR, now=now
            ).all_values(),
            [
                parser.isoparse("2021-08-24T21:00:00Z"),
                parser.isoparse("2021-08-24T22:00:00Z"),
                parser.isoparse("2021-08-24T23:00:00Z"),
                parser.isoparse("2021-08-25T00:00:00Z"),
            ],
        )

    def test_date_to_explicit(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = InsightDateRange(
            date_from="2021-02-25T12:25:23.000Z", date_to="2021-04-25T10:59:23.000Z", explicitDate=True
        )
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-02-25T12:25:23.000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-04-25T10:59:23.000Z"))

    def test_yesterday(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = InsightDateRange(date_from="-1dStart", date_to="-1dEnd", explicitDate=False)

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.HOUR, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-24T00:00:00.000000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-24T23:59:59.999999Z"))

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-24T00:00:00.000000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-24T23:59:59.999999Z"))


class TestQueryDateRangeWithIntervals(APIBaseTest):
    def setUp(self):
        self.now = parser.isoparse("2021-08-25T00:00:00.000Z")
        self.total_intervals = 5

    def test_constructor_initialization(self):
        query = QueryDateRangeWithIntervals(None, self.total_intervals, self.team, IntervalType.DAY, self.now)
        self.assertEqual(query.total_intervals, self.total_intervals)

    def test_determine_time_delta_valid(self):
        delta = QueryDateRangeWithIntervals.determine_time_delta(5, "day")
        self.assertEqual(delta, timedelta(days=5))

    def test_determine_time_delta_invalid_period(self):
        with self.assertRaises(ValueError):
            QueryDateRangeWithIntervals.determine_time_delta(5, "decade")

    def test_date_from_day_interval(self):
        query = QueryDateRangeWithIntervals(None, 2, self.team, IntervalType.DAY, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-24T00:00:00Z"))

    def test_date_from_hour_interval(self):
        query = QueryDateRangeWithIntervals(None, 48, self.team, IntervalType.HOUR, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-23T01:00:00Z"))

    def test_date_from_week_interval_starting_monday(self):
        self.team.week_start_day = WeekStartDay.MONDAY
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.WEEK, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))

    def test_date_from_week_interval_starting_sunday(self):
        self.team.week_start_day = WeekStartDay.SUNDAY
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.WEEK, self.now)
        self.assertEqual(query.date_from(), parser.isoparse("2021-08-22T00:00:00Z"))

    def test_date_to_day_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.DAY, self.now)
        self.assertEqual(query.date_to(), parser.isoparse("2021-08-26T00:00:00Z"))

    def test_date_to_hour_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.HOUR, self.now)
        self.assertEqual(query.date_to(), parser.isoparse("2021-08-25T01:00:00Z"))

    def test_get_start_of_interval_hogql_day_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.DAY, self.now)
        expected_expr = ast.Call(name="toStartOfDay", args=[ast.Constant(value=query.date_from())])
        self.assertEqual(query.get_start_of_interval_hogql(), expected_expr)

    def test_get_start_of_interval_hogql_hour_interval(self):
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.HOUR, self.now)
        expected_expr = ast.Call(name="toStartOfHour", args=[ast.Constant(value=query.date_from())])
        self.assertEqual(query.get_start_of_interval_hogql(), expected_expr)

    def test_get_start_of_interval_hogql_week_interval(self):
        self.team.week_start_day = WeekStartDay.MONDAY
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.WEEK, self.now)
        week_mode = WeekStartDay(self.team.week_start_day or 0).clickhouse_mode
        expected_expr = ast.Call(
            name="toStartOfWeek", args=[ast.Constant(value=query.date_from()), ast.Constant(value=int(week_mode))]
        )
        self.assertEqual(query.get_start_of_interval_hogql(), expected_expr)

    def test_get_start_of_interval_hogql_with_source(self):
        source_expr = ast.Constant(value="2021-08-25T00:00:00.000Z")
        query = QueryDateRangeWithIntervals(None, 1, self.team, IntervalType.DAY, self.now)
        expected_expr = ast.Call(name="toStartOfDay", args=[source_expr])
        self.assertEqual(query.get_start_of_interval_hogql(source=source_expr), expected_expr)
