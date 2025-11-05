import json

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from posthog.constants import FILTER_TEST_ACCOUNTS, TRENDS_LIFECYCLE
from posthog.models import Action, Filter
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.instance_setting import get_instance_setting
from posthog.queries.trends.trends import Trends


def create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name")
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": event_name}])
    return action


class TestLifecycleBase(ClickhouseTestMixin, APIBaseTest):
    def assertLifecycleResults(self, results, expected):
        sorted_results = [
            {"status": r["status"], "data": r["data"]} for r in sorted(results, key=lambda r: r["status"])
        ]
        sorted_expected = sorted(expected, key=lambda r: r["status"])

        self.assertListEqual(sorted_results, sorted_expected)


class TestLifecycle(TestLifecycleBase):
    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "p1" else {}),
                        },
                    )
                )
            for timestamp in timestamps:
                _create_event(team=self.team, event=event, distinct_id=id, timestamp=timestamp)
        return person_result

    def test_lifecycle_trend(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_any_event(self):
        self._create_events(
            event="$pageview",
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
            ],
        )
        self._create_events(
            event="$other",
            data=[
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ],
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": None, "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_with_zero_person_ids(self):
        # only a person-on-event test
        if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            return True

        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p5",
            timestamp="2020-01-13T12:00:00Z",
            person_id="00000000-0000-0000-0000-000000000000",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p5",
            timestamp="2020-01-14T12:00:00Z",
            person_id="00000000-0000-0000-0000-000000000000",
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_prop_filtering(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-13T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-15T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-17T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-19T12:00:00Z",
            properties={"$number": 1},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p4",
            timestamp="2020-01-15T12:00:00Z",
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    "properties": [{"key": "$number", "value": 1}],
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

        #  entities filtering
        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [
                        {
                            "properties": [{"key": "$number", "value": 1}],
                            "id": "$pageview",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_person_prop_filtering(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-13T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-15T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-17T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-19T12:00:00Z",
            properties={"$number": 1},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p4",
            timestamp="2020-01-15T12:00:00Z",
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [
                        {
                            "id": "$pageview",
                            "type": "events",
                            "order": 0,
                            "properties": [{"key": "name", "value": "p1", "type": "person"}],
                        }
                    ],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trends_distinct_id_repeat(self):
        with freeze_time("2020-01-12T12:00:00Z"):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["p1", "another_p1"],
                properties={"name": "p1"},
            )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="another_p1",
            timestamp="2020-01-14T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-15T12:00:00Z",
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-17T12:00:00Z",
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-19T12:00:00Z",
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -1, 0, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 1, 0, 0, 1, 0, 1]},
                {"status": "returning", "data": [0, 0, 0, 1, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_people(self):
        people = self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        p1 = people[0]

        result = self.client.get(
            "/api/person/lifecycle",
            data={
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
                "shown_as": TRENDS_LIFECYCLE,
                "lifecycle_type": "returning",
                "target_date": "2020-01-13T00:00:00Z",
            },
        ).json()

        self.assertEqual(len(result["results"][0]["people"]), 1)
        self.assertEqual(result["results"][0]["people"][0]["uuid"], str(p1.uuid))

        dormant_result = self.client.get(
            "/api/person/lifecycle",
            data={
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
                "shown_as": TRENDS_LIFECYCLE,
                "lifecycle_type": "dormant",
                "target_date": "2020-01-13T00:00:00Z",
            },
        ).json()

        self.assertEqual(len(dormant_result["results"][0]["people"]), 2)

        dormant_result = self.client.get(
            "/api/person/lifecycle",
            data={
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
                "shown_as": TRENDS_LIFECYCLE,
                "lifecycle_type": "dormant",
                "target_date": "2020-01-14T00:00:00Z",
            },
        ).json()

        self.assertEqual(len(dormant_result["results"][0]["people"]), 1)

    def test_lifecycle_trend_people_paginated(self):
        with freeze_time("2020-01-15T12:00:00Z"):
            for i in range(150):
                person_id = "person{}".format(i)
                _create_person(team_id=self.team.pk, distinct_ids=[person_id])
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=person_id,
                    timestamp="2020-01-15T12:00:00Z",
                )
        # even if set to hour 6 it should default to beginning of day and include all pageviews above
        result = self.client.get(
            "/api/person/lifecycle",
            data={
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
                "shown_as": TRENDS_LIFECYCLE,
                "lifecycle_type": "new",
                "target_date": "2020-01-15T00:00:00Z",
            },
        ).json()
        self.assertEqual(len(result["results"][0]["people"]), 100)

        second_result = self.client.get(result["next"]).json()
        self.assertEqual(len(second_result["results"][0]["people"]), 50)

    def test_lifecycle_trend_action(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        pageview_action = create_action(team=self.team, name="$pageview", event_name="$pageview")

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "actions": [{"id": pageview_action.pk, "type": "actions", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_all_time(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        with freeze_time("2020-01-17T13:01:01Z"):
            result = Trends().run(
                Filter(
                    data={
                        "date_from": "all",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -1, 0, 0, -2, -1, 0, -2, 0]},
                {"status": "new", "data": [1, 0, 1, 1, 0, 0, 1, 0, 0]},
                {"status": "returning", "data": [0, 0, 0, 1, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 0, 1, 0, 1]},
            ],
        )

    def test_lifecycle_trend_weeks(self):
        # lifecycle weeks rounds the date to the nearest following week  2/5 -> 2/10
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-02-01T12:00:00Z",
                        "2020-02-05T12:00:00Z",
                        "2020-02-10T12:00:00Z",
                        "2020-02-15T12:00:00Z",
                        "2020-02-27T12:00:00Z",
                        "2020-03-02T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-02-11T12:00:00Z", "2020-02-18T12:00:00Z"]),
                ("p3", ["2020-02-12T12:00:00Z"]),
                ("p4", ["2020-02-27T12:00:00Z"]),
            ]
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-02-05T00:00:00Z",
                    "date_to": "2020-03-09T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    "interval": "week",
                }
            ),
            self.team,
        )

        self.assertEqual(
            result[0]["days"],
            [
                "2020-02-03",
                "2020-02-10",
                "2020-02-17",
                "2020-02-24",
                "2020-03-02",
                "2020-03-09",
            ],
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, -2, -1, -1, -1]},
                {"status": "new", "data": [0, 2, 0, 1, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 0]},
                {"status": "returning", "data": [1, 1, 1, 0, 1, 0]},
            ],
        )

    def test_lifecycle_trend_months(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-02-12T12:00:00Z",
                        "2020-03-13T12:00:00Z",
                        "2020-05-15T12:00:00Z",
                        "2020-07-17T12:00:00Z",
                        "2020-09-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2019-12-09T12:00:00Z", "2020-02-12T12:00:00Z"]),
                ("p3", ["2020-02-12T12:00:00Z"]),
                ("p4", ["2020-05-15T12:00:00Z"]),
            ]
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-02-01T00:00:00Z",
                    "date_to": "2020-09-01T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    "interval": "month",
                }
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_filter_test_accounts(self):
        self._create_events(
            data=[
                (
                    "p1",  # p1 gets test@posthog.com as email and gets filtered out
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        result = Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    FILTER_TEST_ACCOUNTS: True,
                },
                team=self.team,
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, 0, 0, -1, 0, 0, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
            ],
        )

        Trends().get_people(
            LifecycleFilter(
                data={
                    "target_date": "2020-01-13T00:00:00Z",
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    FILTER_TEST_ACCOUNTS: True,
                    "lifecycle_type": "dormant",
                },
                team=self.team,
            ),
            self.team,
        )

    @snapshot_clickhouse_queries
    def test_timezones(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T23:00:00Z",
                        "2020-01-12T01:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        filter_data = {
            "date_from": "2020-01-12",
            "date_to": "2020-01-19",
            "events": [{"id": "$pageview", "type": "events", "order": 0}],
            "shown_as": TRENDS_LIFECYCLE,
        }
        result = Trends().run(
            Filter(data=filter_data),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

        self.team.timezone = "US/Pacific"
        self.team.save()

        result_pacific = Trends().run(
            Filter(data=filter_data),
            self.team,
        )
        self.assertLifecycleResults(
            result_pacific,
            [
                {
                    "status": "dormant",
                    "data": [-1.0, -2.0, -1.0, 0.0, -2.0, 0.0, -1.0, 0.0],
                },
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 1, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
            ],
        )

    # Ensure running the query with sampling works + generate a snapshot that shows sampling in the query
    @snapshot_clickhouse_queries
    def test_sampling(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        Trends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    "sampling_factor": 0.1,
                }
            ),
            self.team,
        )
