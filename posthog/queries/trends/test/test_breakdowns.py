from datetime import datetime

from posthog.models import Filter
from posthog.queries.trends.trends import Trends
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for


class TestBreakdowns(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_session_breakdown(self):
        journey = {
            # Duration 0
            "person1": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$session_id": "1"},
                },
            ],
            # Duration 60 seconds
            "person2": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {"$session_id": "2"},
                },
                {
                    "event": "finished movie",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {"$session_id": "2"},
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
                    "properties": {"$session_id": "3"},
                },
                {
                    "event": "finished movie",
                    "timestamp": datetime(2020, 1, 2, 0, 0, 31),
                    "properties": {"$session_id": "3"},
                },
            ],
            # Duration 120 seconds, with 2 events counted
            "person4": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 12, 1),
                    "properties": {"$session_id": "4"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 12, 3),
                    "properties": {"$session_id": "4"},
                },
            ],
            # Duration 180 seconds, with 2 events counted, each in a different day bucket
            "person4": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 4, 23, 59),
                    "properties": {"$session_id": "4"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 0, 2),
                    "properties": {"$session_id": "4"},
                },
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

        response = Trends().run(
            Filter(
                data={
                    "events": [{"id": "watched movie", "name": "watched movie", "type": "events"},],
                    "breakdown": "$session_duration",
                    "breakdown_type": "session",
                    "date_from": "2020-01-02T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                }
            ),
            self.team,
        )

        self.assertEqual(
            [(item["breakdown_value"], item["count"], item["data"]) for item in response],
            [
                (0, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (60, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (91, 1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (180, 2.0, [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
        )
