from datetime import datetime, timedelta
from typing import Dict

from freezegun import freeze_time

from posthog.models import Filter
from posthog.queries.trends.trends import Trends
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for


@freeze_time("2022-11-09T21:14")
class TestBreakdownsWithInterval(ClickhouseTestMixin, APIBaseTest):
    """
    Two weeks of data, broken down by "some property" and interval "week"
    Not all broken down series have a value for each of the weeks

    freeze time to the 9th of November (a wednesday) and query for "-7d"
    so that the weeks are:
    - week 1: 30th of October - 5th of November (week containing another four of the seven days)
    - week 2: 6th - 12th of November (week containing three of the seven days)

    """

    def setUp(self):
        super().setUp()

        self.week_one = datetime(2022, 10, 30, 12, 1)  # sunday
        self.week_two = datetime(2022, 11, 6, 12, 1)  # sunday

        journey = {
            # count of 1 for each week from person 1 for "some property" = "a"
            "person1": [
                {
                    "event": "watched movie",
                    "properties": {"$some_property": "a"},
                    "timestamp": self.week_one,
                },
                {"event": "watched movie", "properties": {"$some_property": "a"}, "timestamp": self.week_two},
            ],
            # count of 1 for week 1 for "some property" = "b"
            "person2": [
                {
                    "event": "watched movie",
                    "properties": {"$some_property": "b"},
                    # why do I need to add 3 days before this result appears?!
                    "timestamp": self.week_one + timedelta(days=3),
                },
            ],
            # count of 1 for week 2 from person 3 for "some property" = "c"
            "person3": [
                {"event": "watched movie", "properties": {"$some_property": "c"}, "timestamp": self.week_two},
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

    def _run(self, extra: Dict = {}, events_extra: Dict = {}):
        response = Trends().run(
            Filter(
                data={
                    "events": [{"id": "watched movie", "name": "watched movie", "type": "events", **events_extra}],
                    "date_from": "-7d",
                    "interval": "week",
                    "breakdown": "$some_property",
                    "breakdown_type": "event",
                    **extra,
                }
            ),
            self.team,
        )
        return response

    @snapshot_clickhouse_queries
    def test_breakdown_by_some_property_by_week_interval(self):
        response = self._run({})

        assert [{"label": r["label"], "days": r["days"], "data": r["data"]} for r in response] == [
            {
                "data": [1.0, 1.0],
                "days": [
                    "2022-10-30",
                    "2022-11-06",
                ],
                "label": "watched movie - a",
            },
            {
                "data": [1.0, 0.0],
                "days": [
                    "2022-10-30",
                    "2022-11-06",
                ],
                "label": "watched movie - b",
            },
            {
                "data": [0.0, 1.0],
                "days": [
                    "2022-10-30",
                    "2022-11-06",
                ],
                "label": "watched movie - c",
            },
        ]
