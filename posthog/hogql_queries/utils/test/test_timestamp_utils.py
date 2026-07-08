import datetime
from zoneinfo import ZoneInfo

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from dateutil import parser
from parameterized import parameterized

from posthog.schema import ActionsNode, DataWarehouseNode, DateRange, EventsNode, IntervalType

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tags_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.timestamp_utils import (
    EARLIEST_EVENT_TIMESTAMP,
    _coerce_to_datetime,
    _get_earliest_timestamp_cache_key,
    format_label_date,
    get_earliest_timestamp_from_series,
    get_earliest_timestamp_unfiltered,
)
from posthog.models.team import WeekStartDay

from products.actions.backend.models.action import Action


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
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)

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
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)
        self.assertEqual(earliest_timestamp, datetime.datetime(2020, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

        earliest_timestamp_pageview = get_earliest_timestamp_from_series(self.team, [EventsNode(event="$pageview")])
        self.assertEqual(earliest_timestamp_pageview, datetime.datetime(2022, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))
        earliest_timestamp_pageleave = get_earliest_timestamp_from_series(self.team, [EventsNode(event="$pageleave")])
        self.assertEqual(earliest_timestamp_pageleave, datetime.datetime(2020, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

    def test_returns_earliest_timestamp_for_all_events(self):
        """Test that event=None returns earliest across ALL events"""
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

        # When event is None, it should return the earliest timestamp across ALL events
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, [EventsNode(event=None)])
        self.assertEqual(earliest_timestamp, datetime.datetime(2020, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

    def test_returns_earliest_timestamp_multiple_actions(self):
        """Test that multiple actions return the earliest timestamp across all actions"""
        action1 = Action.objects.create(team=self.team, name="Action 1", steps_json=[{"event": "$pageview"}])
        action2 = Action.objects.create(team=self.team, name="Action 2", steps_json=[{"event": "$pageleave"}])

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageleave",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        series = [ActionsNode(id=action1.id), ActionsNode(id=action2.id)]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)
        self.assertEqual(earliest_timestamp, datetime.datetime(2020, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

    def test_returns_earliest_timestamp_mixed_nodes(self):
        """Test that mixing EventsNode and ActionsNode returns earliest timestamp across all"""
        action = Action.objects.create(team=self.team, name="Action 1", steps_json=[{"event": "$pageview"}])

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageleave",
            distinct_id="person1",
            timestamp="2019-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        series: list[ActionsNode | EventsNode] = [ActionsNode(id=action.id), EventsNode(event="$pageleave")]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)
        self.assertEqual(earliest_timestamp, datetime.datetime(2019, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

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
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)

        # create an earlier event to test caching
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
        )
        flush_persons_and_events()

        # should still return the earliest timestamp from the first query
        cached_earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)
        self.assertEqual(cached_earliest_timestamp, earliest_timestamp)

    @freeze_time("2021-01-21")
    def test_unfiltered_earliest_timestamp_returns_earliest_event(self):
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2020-01-04T14:10:00Z")
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2020-01-06T14:10:00Z")
        flush_persons_and_events()

        assert get_earliest_timestamp_unfiltered(self.team) == datetime.datetime(
            2020, 1, 4, 14, 10, tzinfo=datetime.UTC
        )

    @freeze_time("2021-01-21")
    def test_unfiltered_earliest_timestamp_floors_at_2015(self):
        # Events before 2015-01-01 are treated as corrupt and ignored.
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="1984-01-06T14:10:00Z")
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2014-01-01T01:00:00Z")
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2015-01-01T01:00:00Z")
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2020-01-04T14:10:00Z")
        flush_persons_and_events()

        assert get_earliest_timestamp_unfiltered(self.team) == datetime.datetime(2015, 1, 1, 1, tzinfo=datetime.UTC)

    @freeze_time("2021-01-21")
    def test_unfiltered_earliest_timestamp_falls_back_when_no_events(self):
        # No events: fall back to now - DEFAULT_EARLIEST_TIME_DELTA (one week).
        assert get_earliest_timestamp_unfiltered(self.team) == datetime.datetime(2021, 1, 14, tzinfo=datetime.UTC)

    @freeze_time("2021-01-21")
    def test_unfiltered_earliest_timestamp_caches_real_result(self):
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2021-01-01T12:00:00Z")
        flush_persons_and_events()

        earliest_timestamp = get_earliest_timestamp_unfiltered(self.team)

        # A later-added earlier event should not change the cached value within the TTL.
        _create_event(team=self.team, event="sign up", distinct_id="1", timestamp="2020-01-01T12:00:00Z")
        flush_persons_and_events()

        assert get_earliest_timestamp_unfiltered(self.team) == earliest_timestamp

    @parameterized.expand(
        [
            # Naive inputs are interpreted in the passed (team) timezone, not UTC.
            (
                "naive_datetime",
                datetime.datetime(2023, 5, 1, 12, 30, 0),
                datetime.datetime(2023, 5, 1, 12, 30, 0, tzinfo=ZoneInfo("America/New_York")),
            ),
            (
                "aware_datetime",
                datetime.datetime(2023, 5, 1, 12, 30, 0, tzinfo=datetime.UTC),
                datetime.datetime(2023, 5, 1, 12, 30, 0, tzinfo=datetime.UTC),
            ),
            (
                "date",
                datetime.date(2023, 5, 1),
                datetime.datetime(2023, 5, 1, 0, 0, 0, tzinfo=ZoneInfo("America/New_York")),
            ),
            (
                "string",
                "2023-05-01 12:30:00",
                datetime.datetime(2023, 5, 1, 12, 30, 0, tzinfo=ZoneInfo("America/New_York")),
            ),
            (
                "date_string",
                "2023-05-01",
                datetime.datetime(2023, 5, 1, 0, 0, 0, tzinfo=ZoneInfo("America/New_York")),
            ),
            ("none", None, EARLIEST_EVENT_TIMESTAMP),
            ("unsupported", 12345, EARLIEST_EVENT_TIMESTAMP),
            ("unparseable_na", "N/A", EARLIEST_EVENT_TIMESTAMP),
            ("unparseable_null", "null", EARLIEST_EVENT_TIMESTAMP),
            ("unparseable_empty", "", EARLIEST_EVENT_TIMESTAMP),
            ("unparseable_freeform", "not a date at all", EARLIEST_EVENT_TIMESTAMP),
        ]
    )
    def test_coerce_to_datetime(self, _name, value, expected):
        result = _coerce_to_datetime(value, ZoneInfo("America/New_York"))
        self.assertEqual(result, expected)
        # Must be timezone-aware so it can be compared against the tz-aware date_to.
        self.assertIsNotNone(result.tzinfo)

    @parameterized.expand(
        [
            ("string_timestamp", "2022-03-15 08:00:00", datetime.datetime(2022, 3, 15, 8, 0, 0, tzinfo=datetime.UTC)),
            ("date_only_string", "2022-03-15", datetime.datetime(2022, 3, 15, 0, 0, 0, tzinfo=datetime.UTC)),
            ("date_object", datetime.date(2022, 3, 15), datetime.datetime(2022, 3, 15, 0, 0, 0, tzinfo=datetime.UTC)),
        ]
    )
    def test_data_warehouse_all_time_resolves_string_timestamp(self, _name, raw_value, expected):
        # Data warehouse tables can return a non-datetime min(timestamp); it must be
        # coerced before reaching QueryDateRange, which calls .strftime() and compares with <.
        node = DataWarehouseNode(
            id="dw_table",
            table_name="dw_table",
            id_field="id",
            distinct_id_field="distinct_id",
            timestamp_field="ts",
        )

        with patch("posthog.hogql_queries.utils.timestamp_utils.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = [[raw_value]]

            earliest_timestamp = get_earliest_timestamp_from_series(self.team, [node])

        self.assertIsInstance(earliest_timestamp, datetime.datetime)
        self.assertEqual(earliest_timestamp, expected)

        query_date_range = QueryDateRange(
            team=self.team,
            date_range=DateRange(date_from="all"),
            interval=IntervalType.DAY,
            now=parser.isoparse("2025-06-21T00:00:00.000Z"),
            earliest_timestamp_fallback=earliest_timestamp,
        )

        # These previously raised AttributeError / TypeError when date_from="all"
        # resolved to a str instead of a datetime.
        self.assertEqual(query_date_range.date_from(), expected)
        self.assertEqual(query_date_range.date_from_str, expected.strftime("%Y-%m-%d %H:%M:%S"))
        # A Date-typed column yields a naive datetime; comparing it against the tz-aware
        # date_to raised "can't compare offset-naive and offset-aware datetimes" here.
        self.assertGreater(len(query_date_range.all_values()), 0)

    @override_settings(IN_UNIT_TESTING=False)
    @patch("posthog.hogql_queries.utils.timestamp_utils._get_earliest_timestamp_from_node")
    def test_multi_node_propagates_query_tags_to_threads(self, mock_node):
        # Multiple nodes resolve their earliest timestamp via ThreadPoolExecutor, which does not
        # inherit contextvars. Without copying the context, the worker threads' sync_execute calls
        # run untagged and raise UntaggedQueryError in dev (DEBUG and not TEST).
        captured: dict[str, object] = {}

        def capture(team, node, user=None):
            captured[node.table_name] = get_query_tags().product
            return datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)

        mock_node.side_effect = capture
        nodes = [
            DataWarehouseNode(id="a", table_name="a", id_field="id", distinct_id_field="id", timestamp_field="ts"),
            DataWarehouseNode(id="b", table_name="b", id_field="id", distinct_id_field="id", timestamp_field="ts"),
        ]

        with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.QUERY):
            get_earliest_timestamp_from_series(self.team, nodes)

        self.assertEqual(captured["a"], Product.MARKETING_ANALYTICS)
        self.assertEqual(captured["b"], Product.MARKETING_ANALYTICS)

    def test_cached_raw_value_is_coerced_on_read(self):
        # Entries cached before the coercion fix shipped hold a raw str/date for up to the
        # TTL window. A cache hit must still pass through _coerce_to_datetime instead of
        # returning the raw value, otherwise downstream date math hits AttributeError/TypeError.
        node = EventsNode(event="$pageview")
        cache_key = _get_earliest_timestamp_cache_key(self.team, node)
        # team timezone is UTC in tests; "2021-03-15" is the pre-fix raw Date/String shape.
        cache.set(cache_key, "2021-03-15", timeout=3600)

        result = get_earliest_timestamp_from_series(self.team, [node])

        self.assertIsInstance(result, datetime.datetime)
        self.assertEqual(result, datetime.datetime(2021, 3, 15, 0, 0, 0, tzinfo=datetime.UTC))

    @parameterized.expand(
        [
            # No caller tags: the earliest-timestamp query must still carry product/feature,
            # otherwise it raises UntaggedQueryError in dev for uncached series.
            ("fills_defaults_when_unset", None, None, Product.PRODUCT_ANALYTICS, Feature.INSIGHT),
            # Caller already attributed the query (e.g. marketing analytics): keep their tags.
            (
                "preserves_caller_tags",
                Product.MARKETING_ANALYTICS,
                Feature.QUERY,
                Product.MARKETING_ANALYTICS,
                Feature.QUERY,
            ),
        ]
    )
    def test_single_path_query_tags(self, _name, caller_product, caller_feature, expected_product, expected_feature):
        captured: dict[str, object] = {}

        def capture(query, team, user=None):
            tags = get_query_tags()
            captured["product"] = tags.product
            captured["feature"] = tags.feature
            result = MagicMock()
            result.results = [[datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)]]
            return result

        with tags_context(product=caller_product, feature=caller_feature):
            with patch(
                "posthog.hogql_queries.utils.timestamp_utils.execute_hogql_query",
                side_effect=capture,
            ):
                get_earliest_timestamp_from_series(self.team, [EventsNode(event="$pageview")])

        self.assertEqual(captured["product"], expected_product)
        self.assertEqual(captured["feature"], expected_feature)
