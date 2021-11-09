import json

from freezegun import freeze_time
from rest_framework.test import APIRequestFactory

from posthog.constants import FILTER_TEST_ACCOUNTS, TRENDS_LIFECYCLE
from posthog.models import Action, ActionStep, Cohort, Event, Filter, Person, Team
from posthog.queries.trends import Trends
from posthog.test.base import APIBaseTest, BaseTest
from posthog.utils import relative_date_parse


# parameterize tests to reuse in EE
def lifecycle_test_factory(trends, event_factory, person_factory, action_factory):
    class TestLifecycle(APIBaseTest):
        def _create_events(self, data):
            person_result = []
            for person in data:
                id = person[0]
                person_result.append(
                    person_factory(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={"name": id, **({"email": "test@posthog.com"} if id == "p1" else {})},
                    ),
                )
                timestamps = person[1]
                for timestamp in timestamps:
                    event_factory(
                        team=self.team, event="$pageview", distinct_id=id, timestamp=timestamp,
                    )
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

            result = trends().run(
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

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, 0, -2, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

        def test_lifecycle_trend_prop_filtering(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$number": 1},
            )
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-12T12:00:00Z",
                properties={"$number": 1},
            )
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-13T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-15T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-17T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-19T12:00:00Z",
                properties={"$number": 1},
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            result = trends().run(
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

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, 0, -1, 0, -1, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [0, 0, 0, 0, 0, 0, 0, 0])

        def test_lifecycle_trends_distinct_id_repeat(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1", "another_p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="another_p1", timestamp="2020-01-14T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            result = trends().run(
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

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])

            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -1, 0, 0, -1, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 1, 0, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 0, 0, 0, 0, 0])

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
            request_factory = APIRequestFactory()
            request = request_factory.get("/person/lifecycle")

            result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team.pk,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "returning",
                request,
            )

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], p1.pk)

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team.pk,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "dormant",
                request,
            )

            self.assertEqual(len(dormant_result), 2)

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team.pk,
                relative_date_parse("2020-01-14T00:00:00Z"),
                "dormant",
                request,
            )

            self.assertEqual(len(dormant_result), 1)

        def test_lifecycle_trend_people_paginated(self):
            for i in range(150):
                person_id = "person{}".format(i)
                person_factory(team_id=self.team.pk, distinct_ids=[person_id])
                event_factory(
                    team=self.team, event="$pageview", distinct_id=person_id, timestamp="2020-01-15T12:00:00Z",
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

            pageview_action = action_factory(team=self.team, name="$pageview")

            result = trends().run(
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

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, 0, -2, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

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
                result = trends().run(
                    Filter(
                        data={
                            "date_from": "all",
                            "events": [{"id": "$pageview", "type": "events", "order": 0}],
                            "shown_as": TRENDS_LIFECYCLE,
                        }
                    ),
                    self.team,
                )
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -1, 0, 0, -2, -1, 0, -2, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 1, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 1, 1, 0, 0, 1, 0, 0])

        def test_lifecycle_trend_weeks(self):
            # lifecycle weeks rounds the date to the nearest following week  2/5 -> 2/10
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-05T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-10T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-27T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-03-02T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-02-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-02-18T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-02-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-02-27T12:00:00Z",
            )

            result = trends().run(
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

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            self.assertTrue(
                result[0]["days"]
                == ["2020-02-02", "2020-02-09", "2020-02-16", "2020-02-23", "2020-03-01", "2020-03-08"]
                or result[0]["days"]
                == ["2020-02-03", "2020-02-10", "2020-02-17", "2020-02-24", "2020-03-02", "2020-03-09"]
            )
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, 0, -2, -1, -1, -1])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [0, 1, 1, 0, 1, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 0])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [0, 2, 0, 1, 0, 0])

        def test_lifecycle_trend_months(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-03-13T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-05-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-07-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-09-19T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2019-12-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-02-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-02-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-05-15T12:00:00Z",
            )

            result = trends().run(
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

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, 0, -2, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

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

            result = trends().run(
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
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, 0, 0, -1, 0, 0, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [0, 0, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

            request_factory = APIRequestFactory()
            request = request_factory.get("/person/lifecycle")

            dormant_result = trends().get_people(
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
                self.team.pk,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "dormant",
                request,
            )

    return TestLifecycle


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    action.calculate_events()
    return action


class TestDjangoLifecycle(lifecycle_test_factory(Trends, Event.objects.create, Person.objects.create, _create_action)):  # type: ignore
    pass
