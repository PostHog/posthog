from datetime import datetime
from typing import Dict

from posthog.models import Filter
from posthog.queries.trends.trends import Trends
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for


class TestBreakdownsByCurrentURL(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        journey = {
            # full URL - no trailing slash
            "person1": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$current_url": "https://example.com", "$pathname": ""},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$current_url": "https://example.com?", "$pathname": "?"},
                },
            ],
            # full URL - trailing slash
            "person2": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$current_url": "https://example.com/", "$pathname": "/"},
                },
            ],
            # path only - no trailing slash
            "person3": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$current_url": "https://example.com/home", "$pathname": "/home"},
                },
            ],
            # path only - trailing slash
            "person4": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$current_url": "https://example.com/home/", "$pathname": "/home/"},
                },
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

    def _run(self, extra: Dict = {}, events_extra: Dict = {}):
        response = Trends().run(
            Filter(
                data={
                    "events": [{"id": "watched movie", "name": "watched movie", "type": "events", **events_extra}],
                    "date_from": "2020-01-02T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    **extra,
                }
            ),
            self.team,
        )
        return response

    @snapshot_clickhouse_queries
    def test_breakdown_by_pathname(self) -> None:
        response = self._run({"breakdown": "$pathname", "breakdown_type": "event", "breakdown_normalize_url": True})

        assert [(item["breakdown_value"], item["count"], item["data"]) for item in response] == [
            ("/", 3.0, [3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("/home", 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]

    @snapshot_clickhouse_queries
    def test_breakdown_by_current_url(self) -> None:
        response = self._run({"breakdown": "$current_url", "breakdown_type": "event", "breakdown_normalize_url": True})

        assert [(item["breakdown_value"], item["count"], item["data"]) for item in response] == [
            ("https://example.com", 3.0, [3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("https://example.com/home", 2.0, [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]
