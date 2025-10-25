from datetime import datetime
from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.constants import TRENDS_TABLE
from posthog.models import Filter
from posthog.queries.trends.breakdown import (
    BREAKDOWN_NULL_NUMERIC_LABEL,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_NUMERIC_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.queries.trends.trends import Trends
from posthog.test.test_journeys import journeys_for


class TestBreakdowns(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        journey = {
            # Duration 0
            "person1": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$session_id": "1",
                        "movie_length": 100,
                        "$current_url": "https://example.com",
                    },
                }
            ],
            # Duration 60 seconds, with 2 events in 1 session
            "person2": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$session_id": "2",
                        "movie_length": 50,
                        "$current_url": "https://example.com",
                    },
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$session_id": "2",
                        "movie_length": 75,
                        "$current_url": "https://example.com/",
                    },
                },
            ],
            # Duration 90 seconds, but session spans query boundary, so only a single event is counted
            "person3": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 1, 23, 59),
                    "properties": {"$session_id": "3"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 0, 0, 0),
                    "properties": {"$session_id": "3", "movie_length": 25},
                },
                {
                    "event": "finished movie",
                    "timestamp": datetime(2020, 1, 2, 0, 0, 31),
                    "properties": {"$session_id": "3"},
                },
            ],
            # Duration 180.5 seconds, with 2 events counted, each in a different day bucket
            "person4": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 4, 23, 59),
                    "properties": {"$session_id": "4", "movie_length": 1000},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 0, 2, 0, 500000),
                    "properties": {"$session_id": "4", "movie_length": 97.5},
                },
            ],
            # Duration 120 seconds, with 2 events counted. Movie length properties are strings
            "person5": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 12, 1),
                    "properties": {"$session_id": "5", "movie_length": "25"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 12, 1),
                    "properties": {"$session_id": "5", "movie_length": 25},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 12, 3),
                    "properties": {"$session_id": "5", "movie_length": "not a number"},
                },
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

    def _run(self, extra: Optional[dict] = None, events_extra: Optional[dict] = None):
        if events_extra is None:
            events_extra = {}
        if extra is None:
            extra = {}
        response = Trends().run(
            Filter(
                data={
                    "events": [
                        {
                            "id": "watched movie",
                            "name": "watched movie",
                            "type": "events",
                            **events_extra,
                        }
                    ],
                    "date_from": "2020-01-02T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    **extra,
                },
                team=self.team,
            ),
            self.team,
        )
        return response

    @snapshot_clickhouse_queries
    def test_breakdown_by_session_duration_of_events(self):
        response = self._run(
            {
                "breakdown": "$session_duration",
                "breakdown_type": "session",
                "properties": [
                    {
                        "key": "$current_url",
                        "operator": "is_not",
                        "value": ["https://test.com"],
                    }
                ],
            }
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (0, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (60, 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (91, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (120, 3.0, [0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (180, 2.0, [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_session_duration_of_events_with_bucketing(self):
        response = self._run(
            {
                "breakdown": "$session_duration",
                "breakdown_type": "session",
                "breakdown_histogram_bin_count": 3,
                "properties": [
                    {
                        "key": "$current_url",
                        "operator": "is_not",
                        "value": ["https://test.com"],
                    }
                ],
            }
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[0.0,69.92]",
                    3.0,
                    [3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[69.92,110.72]",
                    1.0,
                    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[110.72,180.01]",
                    5.0,
                    [0.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_session_duration_of_events_single_aggregate(self):
        response = self._run(
            {
                "breakdown": "$session_duration",
                "breakdown_type": "session",
                "breakdown_histogram_bin_count": 3,
                "display": TRENDS_TABLE,
            }
        )

        self.assertEqual(
            [(item["breakdown_value"], item["aggregated_value"]) for item in response],
            [("[0.0,69.92]", 3), ("[69.92,110.72]", 1), ("[110.72,180.01]", 5)],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_session_duration_of_unique_sessions(self):
        response = self._run(
            {"breakdown": "$session_duration", "breakdown_type": "session"},
            events_extra={"math": "unique_session"},
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (0, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (60, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (91, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (120, 1.0, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (180, 2.0, [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_session_duration_of_unique_sessions_with_bucketing(self):
        response = self._run(
            {
                "breakdown": "$session_duration",
                "breakdown_type": "session",
                "breakdown_histogram_bin_count": 3,
            },
            events_extra={"math": "unique_session"},
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[0.0,69.92]",
                    2.0,
                    [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[69.92,110.72]",
                    1.0,
                    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[110.72,180.01]",
                    3.0,
                    [0.0, 0.0, 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_event_property_with_bucketing(self):
        response = self._run(
            {
                "breakdown": "movie_length",
                "breakdown_type": "event",
                "breakdown_histogram_bin_count": 3,
            }
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[25.0,66.25]",
                    4.0,
                    [2.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[66.25,98.37]",
                    2.0,
                    [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[98.37,1000.01]",
                    2.0,
                    [1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_event_property_of_unique_sessions_with_bucketing(self):
        response = self._run(
            {
                "breakdown": "movie_length",
                "breakdown_type": "event",
                "breakdown_histogram_bin_count": 3,
            },
            events_extra={"math": "unique_session"},
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[25.0,66.25]",
                    3.0,
                    [2.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[66.25,98.37]",
                    2.0,
                    [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "[98.37,1000.01]",
                    2.0,
                    [1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
        )

    def test_breakdown_by_event_property_with_bucketing_and_duplicate_buckets(self):
        journey = {
            "person1": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"episode_length": 300},
                }
            ],
            "person2": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 4, 12, 1),
                    "properties": {"episode_length": 300},
                }
            ],
            "person3": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 6, 12, 1),
                    "properties": {"episode_length": 300},
                }
            ],
            "person4": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 8, 12, 1),
                    "properties": {"episode_length": 300},
                }
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

        # only one unique value, means all quantiles are the same

        response = Trends().run(
            Filter(
                data={
                    "events": [{"id": "watched tv", "name": "watched tv", "type": "events"}],
                    "date_from": "2020-01-02T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "episode_length",
                    "breakdown_type": "event",
                    "breakdown_histogram_bin_count": 5,
                }
            ),
            self.team,
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[300.0,300.01]",
                    4.0,
                    [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                )
            ],
        )

    def test_breakdown_by_event_property_with_bucketing_and_single_bucket(self):
        journey = {
            "person1": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"episode_length": 300},
                }
            ],
            "person2": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 4, 12, 1),
                    "properties": {"episode_length": 300},
                }
            ],
            "person3": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 5, 12, 1),
                    "properties": {"episode_length": 320},
                }
            ],
            "person4": [
                {
                    "event": "watched tv",
                    "timestamp": datetime(2020, 1, 6, 12, 1),
                    "properties": {"episode_length": 305},
                }
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

        response = Trends().run(
            Filter(
                data={
                    "events": [{"id": "watched tv", "name": "watched tv", "type": "events"}],
                    "date_from": "2020-01-02T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "episode_length",
                    "breakdown_type": "event",
                    "breakdown_histogram_bin_count": 1,
                }
            ),
            self.team,
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[300.0,320.01]",
                    4.0,
                    [1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                )
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_event_property_with_entity_session_filter(self):
        response = self._run(
            {"breakdown": "$current_url", "breakdown_type": "event"},
            events_extra={
                "properties": [
                    {
                        "key": "$session_duration",
                        "type": "session",
                        "operator": "gt",
                        "value": 30,
                    }
                ]
            },
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_STRING_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (
                    "https://example.com",
                    1.0,
                    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                (
                    "https://example.com/",
                    1.0,
                    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_histogram_by_missing_property_regression(self):
        response = self._run(
            {
                "breakdown": "this_property_does_not_exist",
                "breakdown_type": "event",
                "breakdown_histogram_bin_count": 10,
            },
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (
                    "[nan,nan]",
                    0.0,
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_numeric_hogql(self):
        response = self._run(
            {
                "breakdown": "length(properties.$current_url)",
                "breakdown_type": "hogql",
                "breakdown_limit": 2,
            },
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_NUMERIC_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (19, 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (BREAKDOWN_OTHER_NUMERIC_LABEL, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_numeric_hogql_hide_other(self):
        response = self._run(
            {
                "breakdown": "length(properties.$current_url)",
                "breakdown_type": "hogql",
                "breakdown_hide_other_aggregation": True,
                "breakdown_limit": 2,
            },
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_NUMERIC_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (19, 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )
        response = self._run(
            {
                "breakdown": "length(properties.$current_url)",
                "breakdown_type": "hogql",
                "breakdown_hide_other_aggregation": True,
                "breakdown_limit": 3,
            },
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_NUMERIC_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (19, 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (20, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_string_hogql(self):
        response = self._run(
            {
                "breakdown": "properties.$current_url",
                "breakdown_type": "hogql",
                "breakdown_limit": 2,
            },
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_STRING_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                ("https://example.com", 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (BREAKDOWN_OTHER_STRING_LABEL, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_string_hogql_hide_other(self):
        response = self._run(
            {
                "breakdown": "properties.$current_url",
                "breakdown_type": "hogql",
                "breakdown_hide_other_aggregation": True,
                "breakdown_limit": 2,
            },
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_STRING_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                ("https://example.com", 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )
        response = self._run(
            {
                "breakdown": "properties.$current_url",
                "breakdown_type": "hogql",
                "breakdown_hide_other_aggregation": True,
                "breakdown_limit": 3,
            },
        )
        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (BREAKDOWN_NULL_STRING_LABEL, 6.0, [1.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                ("https://example.com", 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                ("https://example.com/", 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )
