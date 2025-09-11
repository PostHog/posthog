from datetime import datetime
from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.models import Filter
from posthog.queries.funnels import ClickhouseFunnel
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
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$current_url": "https://example.com?",
                        "$pathname": "?",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 3),
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
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$current_url": "https://example.com#",
                        "$pathname": "#",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 3),
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
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
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
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$current_url": "https://example.com/home#",
                        "$pathname": "/home#",
                    },
                },
                # all the things
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 3),
                    "properties": {
                        "$current_url": "https://example.com/home/?#",
                        "$pathname": "/home/?#",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 4),
                },
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

    def _run(self, extra: Optional[dict] = None, events_extra: Optional[dict] = None):
        if events_extra is None:
            events_extra = {}
        if extra is None:
            extra = {}
        response = ClickhouseFunnel(
            Filter(
                data={
                    "events": [
                        {
                            "id": "watched movie",
                            "name": "watched movie",
                            "type": "events",
                            "order": 0,
                            **events_extra,
                        },
                        {
                            "id": "terminate funnel",
                            "name": "terminate funnel",
                            "type": "events",
                            "order": 1,
                            **events_extra,
                        },
                    ],
                    "funnel_viz_type": "steps",
                    "insight": "FUNNELS",
                    "date_from": "2020-01-02T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown_limit": 100,  # never have other
                    **extra,
                }
            ),
            self.team,
        ).run()
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

        actual = []
        for breakdown_value in response:
            for funnel_step in breakdown_value:
                actual.append(
                    (
                        funnel_step["name"],
                        funnel_step["count"],
                        funnel_step["breakdown"],
                    )
                )
        assert actual == [
            ("watched movie", 2, ["/"]),
            ("terminate funnel", 2, ["/"]),
            ("watched movie", 2, ["/home"]),
            ("terminate funnel", 2, ["/home"]),
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

        actual = []
        for breakdown_value in response:
            for funnel_step in breakdown_value:
                actual.append(
                    (
                        funnel_step["name"],
                        funnel_step["count"],
                        funnel_step["breakdown"],
                    )
                )

        assert actual == [
            ("watched movie", 2, ["https://example.com/home"]),
            ("terminate funnel", 2, ["https://example.com/home"]),
            ("watched movie", 2, ["https://example.com"]),
            ("terminate funnel", 2, ["https://example.com"]),
        ]
