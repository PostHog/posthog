import datetime
from django.core.cache import cache
from django.test import override_settings
from dateutil import parser

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.models.team import WeekStartDay
from posthog.schema import DateRange, IntervalType
from posthog.test.base import APIBaseTest

from posthog.hogql_queries.utils.timestamp_utils import get_earliest_timestamp_from_series
from posthog.schema import EventsNode
from posthog.test.base import _create_event, flush_persons_and_events, ClickhouseDestroyTablesMixin


@override_settings(IN_UNIT_TESTING=True)
class TestTimestampUtils(APIBaseTest, ClickhouseDestroyTablesMixin):
    def tearDown(self):
        super().tearDown()
        # Clear the cache after each test to avoid interference
        cache.clear()

    def test_format_label_date_with_hour_interval(self):
        date = datetime.datetime(2022, 12, 31, 23, 59)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2022-12-30 00:00:00", date_to="2023-01-01 23:59:59"),
            interval=IntervalType.HOUR,
            now=parser.isoparse("2025-06-21T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)
        assert formatted_date == "31-Dec 23:59"

    def test_format_label_date_with_month_interval(self):
        date = datetime.datetime(2022, 12, 31)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2022-12-01 00:00:00", date_to="2022-12-31 23:59:59"),
            interval=IntervalType.MONTH,
            now=parser.isoparse("2025-06-21T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)
        assert formatted_date == "Dec 2022"

    def test_format_label_date_with_day_interval(self):
        date = datetime.datetime(2022, 12, 31)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2022-01-01 00:00:00", date_to="2022-12-31 23:59:59"),
            interval=IntervalType.DAY,
            now=parser.isoparse("2025-06-21T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)
        assert formatted_date == "31-Dec-2022"

    def test_format_label_date_with_date_input(self):
        date = datetime.date(2022, 12, 31)

        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2022-01-01 00:00:00", date_to="2022-12-31 23:59:59"),
            interval=IntervalType.DAY,
            now=parser.isoparse("2025-06-21T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)  # type: ignore[arg-type]
        assert formatted_date == "31-Dec-2022"

    def test_format_label_date_with_missing_interval(self):
        date = datetime.datetime(2022, 12, 31)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2022-01-01 00:00:00", date_to="2022-12-31 23:59:59"),
            interval=None,
            now=parser.isoparse("2025-06-21T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)
        assert formatted_date == "31-Dec-2022"

    def test_format_label_date_with_week_interval_and_date_input(self):
        date = datetime.date(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-01-01 00:00:00", date_to="2025-06-30 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)  # type: ignore[arg-type]
        assert formatted_date == "8–14 Jun"

    def test_format_label_date_with_week_interval_same_month_and_year(self):
        date = datetime.datetime(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-01-01 00:00:00", date_to="2025-06-30 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)
        assert formatted_date == "8–14 Jun"

    def test_format_label_date_with_week_interval_different_months_same_year(self):
        date = datetime.datetime(2025, 4, 30)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-04-01 00:00:00", date_to="2025-06-30 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)

        # Since the week starts on Sunday, the week containing April 30, 2025, is from April 27 to May 3.
        assert formatted_date == "27-Apr – 3-May"

    def test_format_label_date_with_week_interval_different_years(self):
        date = datetime.datetime(2025, 1, 1)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2024-12-01 00:00:00", date_to="2025-01-31 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)

        # Since the week starts on Sunday, the week containing January 5, 2025, is from December 29, 2024, to January 4, 2025.
        assert formatted_date == "29-Dec-2024 – 4-Jan-2025"

    def test_format_label_date_with_week_interval_same_day_start_and_end(self):
        date = datetime.datetime(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-06-11 00:00:00", date_to="2025-06-11 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)

        assert formatted_date == "11-Jun-2025"

    def test_format_label_date_with_week_interval_bounded_by_date_range(self):
        date = datetime.datetime(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-06-10 00:00:00", date_to="2025-06-12 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)

        assert formatted_date == "10–12 Jun"

    def test_format_label_date_with_week_interval_date_to_before_from(self):
        date = datetime.datetime(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-06-01 00:00:00", date_to="2025-06-07 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.SUNDAY)

        # Since the week starts on Sunday, the week containing June 11, 2025, is from June 8 to June 14.
        # The date_to limits the range to June 7, so we can't return a whole week.
        # The expected output should be the week start date, which is June 8, 2025.

        assert formatted_date == "8-Jun-2025"

    def test_format_label_date_with_week_interval_default_week_start(self):
        date = datetime.datetime(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-06-01 00:00:00", date_to="2025-06-30 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range)

        # Default week start is Sunday
        assert formatted_date == "8–14 Jun"

    def test_format_label_date_with_week_interval_monday_week_start(self):
        date = datetime.datetime(2025, 6, 11)
        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="2025-06-01 00:00:00", date_to="2025-06-30 23:59:59"),
            interval=IntervalType.WEEK,
            now=parser.isoparse("2025-06-30T00:00:00.000Z"),
        )
        formatted_date = format_label_date(date, query_date_range, WeekStartDay.MONDAY)

        # Since the week starts on Monday, the week containing June 11, 2025, is from June 9 to June 15.
        assert formatted_date == "9–15 Jun"

    def test_returns_earliest_timestamp_one_node(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2021-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        series = [
            EventsNode(event="$pageview"),
        ]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)  # type: ignore

        self.assertEqual(earliest_timestamp, datetime.datetime(2021, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

    def test_returns_earliest_timestamp_series_nodes(self):
        _create_event(
            team=self.team,
            event="$pageleave",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        series = [
            EventsNode(event="$pageview"),
            EventsNode(event="$pageleave"),
        ]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)  # type: ignore

        self.assertEqual(earliest_timestamp, datetime.datetime(2020, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

        # earliest timestamp is the same for all events regardless of the type
        earliest_timestamp_pageview = get_earliest_timestamp_from_series(self.team, [EventsNode(event="$pageview")])
        self.assertEqual(earliest_timestamp, earliest_timestamp_pageview)
        earliest_timestamp_pageleave = get_earliest_timestamp_from_series(self.team, [EventsNode(event="$pageleave")])
        self.assertEqual(earliest_timestamp, earliest_timestamp_pageleave)

    def test_caches_earliest_timestamp(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2021-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        series = [
            EventsNode(event="$pageview"),
        ]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)  # type: ignore

        # create an earlier event to test caching
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        # should still return the earliest timestamp from the first query
        cached_earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)  # type: ignore

        self.assertEqual(cached_earliest_timestamp, earliest_timestamp)
