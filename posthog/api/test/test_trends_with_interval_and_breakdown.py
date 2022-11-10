from datetime import datetime, timedelta

from freezegun import freeze_time

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from posthog.test.test_journeys import journeys_for


@freeze_time("2022-11-09T21:14")
class TestTrendsWithIntervalAndBreakdown(ClickhouseTestMixin, APIBaseTest):
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
            # data from before the range
            "person0": [
                {
                    "event": "watched movie",
                    "properties": {"$some_property": "a"},
                    "timestamp": self.week_one - timedelta(days=4),
                },
            ],
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

    def test_from_here(self) -> None:
        self.team.timezone = "UTC"
        self.team.save()

        filter_params = [
            "insight=TRENDS",
            'events=[{"id":"watched movie","name":"watched movie","type":"events","order":0}]',
            "display=ActionsLineGraph",
            "interval=week",
            "breakdown=$some_property",
            "breakdown_type=event",
            "data_from=-7d",
            "refresh=true",
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/insights/trend/?{'&'.join(filter_params)}").json()
        assert [{"label": r["label"], "days": r["days"], "data": r["data"]} for r in response["result"]] == [
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

    def test_from_us_pacific(self) -> None:
        """
        In the UI this actually returns three week-groups of data 🤯
        """
        self.team.timezone = "US/Pacific"  # GMT -8
        self.team.save()

        filter_params = [
            "insight=TRENDS",
            'events=[{"id":"watched movie","name":"watched movie","type":"events","order":0}]',
            "display=ActionsLineGraph",
            "interval=week",
            "breakdown=$some_property",
            "breakdown_type=event",
            "data_from=-7d",
            "refresh=true",
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/insights/trend/?{'&'.join(filter_params)}").json()
        assert [{"label": r["label"], "days": r["days"], "data": r["data"]} for r in response["result"]] == [
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
