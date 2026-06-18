from datetime import timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from dateutil import parser
from parameterized import parameterized

from posthog.schema import DateRange, IntervalType

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange, QueryDateRangeWithIntervals
from posthog.models.team import WeekStartDay


class TestQueryDateRange(APIBaseTest):
    def test_parsed_date(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25T23:59:59.999999Z"))

    def test_parsed_date_hour(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.HOUR, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23T00:00:00Z"))
        self.assertEqual(
            query_date_range.date_to(), parser.isoparse("2021-08-25T00:59:59.999999Z")
        )  # ensure last hour is included

    def test_parsed_date_middle_of_hour(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="2021-08-23 05:00:00", date_to="2021-08-26 07:00:00")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.HOUR, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-23 05:00:00Z"))
        self.assertEqual(
            query_date_range.date_to(), parser.isoparse("2021-08-26 07:00:00Z")
        )  # ensure last hour is included

    def test_parsed_date_week(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-7d")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.WEEK, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-18 00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25 23:59:59.999999Z"))

    def test_all_values(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=DateRange(date_from="-20h"), interval=IntervalType.DAY, now=now
            ).all_values(),
            [parser.isoparse("2021-08-24T00:00:00Z"), parser.isoparse("2021-08-25T00:00:00Z")],
        )
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=DateRange(date_from="-20d"), interval=IntervalType.WEEK, now=now
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
                team=self.team, date_range=DateRange(date_from="-20d"), interval=IntervalType.WEEK, now=now
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
                team=self.team, date_range=DateRange(date_from="-50d"), interval=IntervalType.MONTH, now=now
            ).all_values(),
            [parser.isoparse("2021-07-01T00:00:00Z"), parser.isoparse("2021-08-01T00:00:00Z")],
        )
        self.assertEqual(
            QueryDateRange(
                team=self.team, date_range=DateRange(date_from="-3h"), interval=IntervalType.HOUR, now=now
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
        date_range = DateRange(
            date_from="2021-02-25T12:25:23.000Z", date_to="2021-04-25T10:59:23.000Z", explicitDate=True
        )
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-02-25T12:25:23.000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-04-25T10:59:23.000Z"))

    def test_yesterday(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-1dStart", date_to="-1dEnd", explicitDate=False)

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.HOUR, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-24T00:00:00.000000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-24T23:59:59.999999Z"))

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-24T00:00:00.000000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-24T23:59:59.999999Z"))

    def test_minute(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-2M", date_to="-1M", explicitDate=False)

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.MINUTE, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-24T23:58:00.000000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-24T23:59:59.999999Z"))

    def test_second(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-120s", date_to="-60s", explicitDate=False)

        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.SECOND, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-24T23:58:00.000000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-24T23:58:59.999999Z"))

    def test_parsed_date_second(self):
        now = parser.isoparse("2021-08-25T12:30:00.000Z")
        date_range = DateRange(date_from="-60s")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.SECOND, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-25T12:29:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25T12:29:59.999999Z"))

    def test_second_interval_with_explicit_date(self):
        now = parser.isoparse("2021-08-25T12:30:45.000Z")
        date_range = DateRange(
            date_from="2021-08-25T12:29:30.000Z", date_to="2021-08-25T12:30:15.000Z", explicitDate=True
        )
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.SECOND, now=now)

        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-25T12:29:30.000Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-25T12:30:15.000Z"))

    def test_align_with_interval_second(self):
        now = parser.isoparse("2021-08-25T12:30:45.123456Z")
        query_date_range = QueryDateRange(team=self.team, date_range=None, interval=IntervalType.SECOND, now=now)

        aligned = query_date_range.align_with_interval(now)
        self.assertEqual(aligned, parser.isoparse("2021-08-25T12:30:45.000000Z"))

    def test_second_interval_count(self):
        now = parser.isoparse("2021-08-25T12:30:00.000Z")
        date_range = DateRange(date_from="-300s", date_to="-0s", explicitDate=False)

        query_date_range = QueryDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.SECOND, interval_count=10, now=now
        )

        values = query_date_range.all_values()
        self.assertEqual(values[0], parser.isoparse("2021-08-25T12:25:00.000000Z"))
        self.assertEqual(values[1], parser.isoparse("2021-08-25T12:25:10.000000Z"))
        self.assertEqual(values[2], parser.isoparse("2021-08-25T12:25:20.000000Z"))
        self.assertEqual(values[-1], parser.isoparse("2021-08-25T12:29:50.000000Z"))
        self.assertEqual(len(values), 30)

    def test_all_values_second_interval(self):
        now = parser.isoparse("2021-08-25T12:30:00.000Z")
        query_date_range = QueryDateRange(
            team=self.team, date_range=DateRange(date_from="-10s"), interval=IntervalType.SECOND, now=now
        )

        values = query_date_range.all_values()
        self.assertEqual(values[0], parser.isoparse("2021-08-25T12:29:50.000000Z"))
        self.assertEqual(values[1], parser.isoparse("2021-08-25T12:29:51.000000Z"))
        self.assertEqual(values[-1], parser.isoparse("2021-08-25T12:29:59.000000Z"))
        self.assertEqual(len(values), 10)

    def test_interval_count(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-66M", date_to="-6M", explicitDate=False)

        query_date_range = QueryDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.MINUTE, interval_count=10, now=now
        )

        self.assertEqual(query_date_range.all_values()[0], parser.isoparse("2021-08-24T22:54:00.000000Z"))
        self.assertEqual(query_date_range.all_values()[1], parser.isoparse("2021-08-24T23:04:00.000000Z"))
        self.assertEqual(query_date_range.all_values()[2], parser.isoparse("2021-08-24T23:14:00.000000Z"))
        self.assertEqual(query_date_range.all_values()[3], parser.isoparse("2021-08-24T23:24:00.000000Z"))
        self.assertEqual(query_date_range.all_values()[4], parser.isoparse("2021-08-24T23:34:00.000000Z"))
        self.assertEqual(query_date_range.all_values()[5], parser.isoparse("2021-08-24T23:44:00.000000Z"))
        self.assertEqual(query_date_range.all_values()[6], parser.isoparse("2021-08-24T23:54:00.000000Z"))

    def test_explicit_timezone(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-1d", date_to=None, explicitDate=False)
        self.team.timezone = "Europe/Berlin"

        query_date_range = QueryDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.MINUTE, interval_count=10, now=now
        )
        query_date_range_utc = QueryDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.MINUTE,
            interval_count=10,
            now=now,
            timezone_info=ZoneInfo("UTC"),
        )

        # the tz shouldn't affect the actual time, should both be equal
        date_to = query_date_range.date_to()
        date_to_utc = query_date_range_utc.date_to()
        self.assertEqual(date_to, date_to_utc)
        assert date_to.tzinfo != date_to_utc.tzinfo
        self.assertEqual(date_to.tzinfo, ZoneInfo("Europe/Berlin"))
        self.assertEqual(date_to_utc.tzinfo, ZoneInfo("UTC"))

    def test_relative_week_date_with_monday_as_week_start_day(self):
        now = parser.isoparse("2025-10-08T00:00:00.000Z")
        self.team.week_start_day = WeekStartDay.MONDAY
        date_range = DateRange(date_from="-1wStart", date_to="-1wEnd")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2025-09-29T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2025-10-05T23:59:59.999999Z"))

        date_range = DateRange(date_from="-2wStart", date_to="-2wEnd")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2025-09-22T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2025-09-28T23:59:59.999999Z"))

    def test_relative_week_date_with_sunday_as_week_start_day(self):
        now = parser.isoparse("2025-10-08T00:00:00.000Z")
        self.team.week_start_day = WeekStartDay.SUNDAY
        date_range = DateRange(date_from="-1wStart", date_to="-1wEnd")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2025-09-28T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2025-10-04T23:59:59.999999Z"))

        date_range = DateRange(date_from="-2wStart", date_to="-2wEnd")
        query_date_range = QueryDateRange(team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now)
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2025-09-21T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2025-09-27T23:59:59.999999Z"))

    def test_pin_now_overrides_initial_now_before_cache(self):
        initial_now = parser.isoparse("2021-08-25T00:00:00.000Z")
        pinned_now = parser.isoparse("2021-07-01T00:00:00.000Z")
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="-7d"),
            interval=IntervalType.DAY,
            now=initial_now,
        )

        query_date_range.pin_now(pinned_now)

        # date_to / date_from must reflect pinned_now, not initial_now
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-07-01T23:59:59.999999Z"))
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-06-24T00:00:00Z"))

    def test_pin_now_raises_after_derived_property_cached(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="-7d"),
            interval=IntervalType.DAY,
            now=now,
        )
        # Trigger the cached_property chain
        _ = query_date_range.date_from()

        with self.assertRaises(RuntimeError) as cm:
            query_date_range.pin_now(parser.isoparse("2021-07-01T00:00:00.000Z"))
        self.assertIn("now_with_timezone", str(cm.exception))


class TestExactTimerange(APIBaseTest):
    INTERVALS = [
        ("day", IntervalType.DAY),
        ("hour", IntervalType.HOUR),
        ("minute", IntervalType.MINUTE),
    ]

    @parameterized.expand(INTERVALS)
    def test_date_to_returns_now_directly_when_exact_timerange_true_and_no_date_to(self, _name, interval):
        now = parser.isoparse("2021-08-25T14:30:45.123456Z")
        qdr = QueryDateRange(
            team=self.team, date_range=DateRange(date_from="-7d"), interval=interval, now=now, exact_timerange=True
        )
        result = qdr.date_to()
        self.assertEqual(result, qdr.now_with_timezone)

    @parameterized.expand(
        [
            ("day", IntervalType.DAY, "2021-08-25T23:59:59.999999Z"),
            ("hour", IntervalType.HOUR, "2021-08-25T14:59:59.999999Z"),
            ("minute", IntervalType.MINUTE, "2021-08-25T14:30:59.999999Z"),
        ]
    )
    def test_date_to_rounds_when_exact_timerange_false_and_no_date_to(self, _name, interval, expected_str):
        now = parser.isoparse("2021-08-25T14:30:45.123456Z")
        qdr = QueryDateRange(
            team=self.team, date_range=DateRange(date_from="-7d"), interval=interval, now=now, exact_timerange=False
        )
        self.assertEqual(qdr.date_to(), parser.isoparse(expected_str))

    def test_date_from_does_not_truncate_when_exact_timerange_true(self):
        now = parser.isoparse("2021-08-25T14:30:45.000Z")
        qdr_exact = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="-48h"),
            interval=IntervalType.DAY,
            now=now,
            exact_timerange=True,
        )
        qdr_normal = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="-48h"),
            interval=IntervalType.DAY,
            now=now,
            exact_timerange=False,
        )
        # exact_timerange=True passes always_truncate=False, preserving minutes/seconds
        self.assertEqual(qdr_exact.date_from(), parser.isoparse("2021-08-23T14:30:45Z"))
        # Without exact_timerange, always_truncate=True rounds to the hour boundary
        self.assertEqual(qdr_normal.date_from(), parser.isoparse("2021-08-23T14:00:00Z"))

    @parameterized.expand(INTERVALS)
    def test_use_start_of_interval_false_when_exact_timerange_true(self, _name, interval):
        now = parser.isoparse("2021-08-25T14:30:45.000Z")
        qdr = QueryDateRange(
            team=self.team, date_range=DateRange(date_from="-7d"), interval=interval, now=now, exact_timerange=True
        )
        self.assertFalse(qdr.use_start_of_interval())


class TestUseStartOfInterval(APIBaseTest):
    @parameterized.expand(
        [
            (
                "explicit_date_returns_false",
                DateRange(date_from="2021-08-20T00:00:00Z", date_to="2021-08-25T00:00:00Z", explicitDate=True),
                IntervalType.DAY,
                False,
            ),
            (
                "none_date_range_returns_true",
                None,
                IntervalType.DAY,
                True,
            ),
            (
                "none_date_from_returns_true",
                DateRange(date_from=None),
                IntervalType.DAY,
                True,
            ),
            (
                "hour_interval_relative_returns_false",
                DateRange(date_from="-3h"),
                IntervalType.HOUR,
                False,
            ),
            (
                "minute_interval_relative_returns_false",
                DateRange(date_from="-30M"),
                IntervalType.MINUTE,
                False,
            ),
            (
                "day_interval_with_hour_delta_returns_false",
                DateRange(date_from="-48h"),
                IntervalType.DAY,
                False,
            ),
            (
                "day_interval_with_day_delta_returns_true",
                DateRange(date_from="-7d"),
                IntervalType.DAY,
                True,
            ),
        ]
    )
    def test_use_start_of_interval(self, _name, date_range, interval, expected):
        now = parser.isoparse("2021-08-25T14:30:00.000Z")
        qdr = QueryDateRange(team=self.team, date_range=date_range, interval=interval, now=now)
        self.assertEqual(qdr.use_start_of_interval(), expected)


class TestMultiHourIntervalConversion(APIBaseTest):
    @parameterized.expand(
        [
            ("count_1_stays_hour", 1, "hour", 1),
            ("count_2_converts_to_minute_120", 2, "minute", 120),
            ("count_3_converts_to_minute_180", 3, "minute", 180),
            ("count_4_converts_to_minute_240", 4, "minute", 240),
        ]
    )
    def test_multi_hour_interval_conversion(self, _name, interval_count, expected_interval_name, expected_count):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        qdr = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="-7d"),
            interval=IntervalType.HOUR,
            now=now,
            interval_count=interval_count,
        )
        self.assertEqual(qdr.interval_name, expected_interval_name)
        self.assertEqual(qdr.interval_count, expected_count)


class TestPreviousPeriodDateFrom(APIBaseTest):
    @parameterized.expand(
        [
            (
                "7d_range",
                DateRange(date_from="-7d"),
                IntervalType.DAY,
                # date_from = 2021-08-18 00:00:00, date_to = 2021-08-25 23:59:59.999999
                # previous = 2021-08-18 - (2021-08-25T23:59:59.999999 - 2021-08-18) = 2021-08-10 00:00:00.000001
                "2021-08-10T00:00:00.000001Z",
            ),
            (
                "custom_explicit",
                DateRange(
                    date_from="2021-08-10T00:00:00Z",
                    date_to="2021-08-20T00:00:00Z",
                    explicitDate=True,
                ),
                IntervalType.DAY,
                # date_from = 2021-08-10, date_to = 2021-08-20, delta = 10 days
                # previous = 2021-08-10 - 10 days = 2021-07-31
                "2021-07-31T00:00:00Z",
            ),
        ]
    )
    def test_previous_period_date_from(self, _name, date_range, interval, expected_str):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        qdr = QueryDateRange(team=self.team, date_range=date_range, interval=interval, now=now)
        self.assertEqual(qdr.previous_period_date_from, parser.isoparse(expected_str))


class TestDateFromAll(APIBaseTest):
    @parameterized.expand(
        [
            ("day_interval", IntervalType.DAY),
            ("hour_interval", IntervalType.HOUR),
        ]
    )
    def test_date_from_all_uses_earliest_timestamp_fallback(self, _name, interval):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        fallback = parser.isoparse("2020-01-01T00:00:00.000Z")
        qdr = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="all"),
            interval=interval,
            now=now,
            earliest_timestamp_fallback=fallback,
        )
        self.assertEqual(qdr.date_from(), fallback)


class TestQueryDateRangeWithIntervals(APIBaseTest):
    def setUp(self):
        self.now = parser.isoparse("2021-08-25T00:00:00.000Z")
        self.lookahead = 5

    def test_constructor_initialization(self):
        query = QueryDateRangeWithIntervals(None, self.lookahead, self.team, IntervalType.DAY, self.now)
        self.assertEqual(query.lookahead, self.lookahead)

    def test_pin_now_works_on_subclass(self):
        initial_now = parser.isoparse("2021-08-25T00:00:00.000Z")
        pinned_now = parser.isoparse("2021-07-01T00:00:00.000Z")
        query = QueryDateRangeWithIntervals(None, 7, self.team, IntervalType.DAY, initial_now)

        query.pin_now(pinned_now)

        # date_to should reflect pinned_now (the subclass's date_to adds one interval
        # and truncates to start of interval, so 2021-07-01 00:00:00 UTC becomes 2021-07-02 00:00:00 UTC)
        self.assertEqual(query.date_to(), parser.isoparse("2021-07-02T00:00:00Z"))

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
