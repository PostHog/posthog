import datetime
from django.core.cache import cache
from django.test import override_settings

from posthog.hogql_queries.utils.timestamp_utils import get_earliest_timestamp_from_series
from posthog.schema import EventsNode
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events, ClickhouseDestroyTablesMixin


@override_settings(IN_UNIT_TESTING=True)
class TestTimestampUtils(APIBaseTest, ClickhouseDestroyTablesMixin):
    def tearDown(self):
        super().tearDown()
        # Clear the cache after each test to avoid interference
        cache.clear()

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
