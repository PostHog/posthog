from datetime import datetime
from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.models import Filter
from posthog.queries.trends.trends import Trends
from posthog.test.test_journeys import journeys_for


class TestBreakdownsByCurrentURL(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        journey = {
            "person1": [
                # no trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com",
                        "$pathname": "",
                    },
                },
                # trailing question mark
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com?",
                        "$pathname": "?",
                    },
                },
            ],
            "person2": [
                # trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/",
                        "$pathname": "/",
                    },
                },
                # trailing hash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com#",
                        "$pathname": "#",
                    },
                },
            ],
            "person3": [
                # no trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/home",
                        "$pathname": "/home",
                    },
                },
            ],
            "person4": [
                # trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/home/",
                        "$pathname": "/home/",
                    },
                },
                # trailing hash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/home#",
                        "$pathname": "/home#",
                    },
                },
                # all the things
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/home/?#",
                        "$pathname": "/home/?#",
                    },
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
                }
            ),
            self.team,
        )
        return response

    @snapshot_clickhouse_queries
    def test_breakdown_by_pathname(self) -> None:
        response = self._run(
            {
                "breakdown": "$pathname",
                "breakdown_type": "event",
                "breakdown_normalize_url": True,
            }
        )

        assert [(item["breakdown_value"], item["count"], item["data"]) for item in response] == [
            ("/", 4.0, [4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("/home", 4.0, [4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]

    @snapshot_clickhouse_queries
    def test_breakdown_by_current_url(self) -> None:
        response = self._run(
            {
                "breakdown": "$current_url",
                "breakdown_type": "event",
                "breakdown_normalize_url": True,
            }
        )

        assert [(item["breakdown_value"], item["count"], item["data"]) for item in response] == [
            (
                "https://example.com",
                4.0,
                [4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ),
            (
                "https://example.com/home",
                4.0,
                [4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ),
        ]
