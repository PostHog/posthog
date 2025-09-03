import json
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE, TRENDS_CUMULATIVE
from posthog.models import Action, Cohort, Organization
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name}])
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    return cohort


class TestPersonTrends(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, use_time=False):
        _create_action(team=self.team, name="no events")

        sign_up_action = _create_action(team=self.team, name="sign up")

        person = _create_person(team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"])
        secondTeam = Organization.objects.bootstrap(None, team_fields={"api_token": "token456"})[2]

        freeze_without_time = ["2019-12-24", "2020-01-01", "2020-01-02"]
        freeze_with_time = [
            "2019-12-24 03:45:34",
            "2020-01-01 00:06:34",
            "2020-01-02 16:34:34",
        ]

        freeze_args = freeze_without_time
        if use_time:
            freeze_args = freeze_with_time

        with freeze_time(freeze_args[0]):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value"},
            )

        with freeze_time(freeze_args[1]):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value"},
            )
            _create_event(team=self.team, event="sign up", distinct_id="anonymous_id")
            _create_event(team=self.team, event="sign up", distinct_id="blabla")
        with freeze_time(freeze_args[2]):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$some_property": "other_value",
                    "$some_numerical_prop": 80,
                },
            )
            _create_event(team=self.team, event="no events", distinct_id="blabla")

            # second team should have no effect
            _create_event(
                team=secondTeam,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value"},
            )

        flush_persons_and_events()
        return sign_up_action, person

    def test_people_cumulative(self):
        with freeze_time("2020-01-01 00:06:34"):
            for i in range(20):
                _create_person(team_id=self.team.pk, distinct_ids=[f"blabla_{i}"])
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"blabla_{i}",
                    properties={"$some_property": "value"},
                )

        with freeze_time("2020-01-05 00:06:34"):
            for i in range(20, 40):
                _create_person(team_id=self.team.pk, distinct_ids=[f"blabla_{i}"])
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"blabla_{i}",
                    properties={"$some_property": "value"},
                )

        with freeze_time("2020-01-15 00:06:34"):
            for i in range(40, 80):
                _create_person(team_id=self.team.pk, distinct_ids=[f"blabla_{i}"])
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"blabla_{i}",
                    properties={"$some_property": "value"},
                )

        event_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-31",
                "interval": "day",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
                "display": "ActionsLineGraphCumulative",
            },
        ).json()
        self.assertEqual(event_response["results"][0]["count"], 80)

        with freeze_time("2020-01-31 00:06:34"):
            event_response = self.client.get(
                f"/api/projects/{self.team.id}/persons/trends/",
                data={
                    "date_from": "-30d",
                    "date_to": "2020-01-31",
                    "interval": "day",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                    "display": "ActionsLineGraphCumulative",
                },
            ).json()
            self.assertEqual(event_response["results"][0]["count"], 80)

    def _create_breakdown_events(self):
        freeze_without_time = ["2020-01-02"]

        _create_action(team=self.team, name="sign up")

        with freeze_time(freeze_without_time[0]):
            for i in range(25):
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": i},
                )

        flush_persons_and_events()

    def test_people_endpoint_paginated(self):
        for index in range(0, 150):
            _create_person(team_id=self.team.pk, distinct_ids=["person" + str(index)])
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person" + str(index),
                timestamp="2020-01-04T12:00:00Z",
            )

        event_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-04",
                "date_to": "2020-01-04",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
            },
        ).json()

        self.assertEqual(len(event_response["results"][0]["people"]), 100)
        event_response_next = self.client.get(event_response["next"]).json()
        self.assertEqual(len(event_response_next["results"][0]["people"]), 50)

    def _create_people_interval_events(self):
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        person2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        person3 = _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        person4 = _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        person5 = _create_person(team_id=self.team.pk, distinct_ids=["person5"])
        person6 = _create_person(team_id=self.team.pk, distinct_ids=["person6"])
        person7 = _create_person(team_id=self.team.pk, distinct_ids=["person7"])

        # solo
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2020-01-04T14:10:00Z",
        )
        # group by hour
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            timestamp="2020-01-04T16:30:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            timestamp="2020-01-04T16:50:00Z",
        )
        # group by min
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person4",
            timestamp="2020-01-04T19:20:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person5",
            timestamp="2020-01-04T19:20:00Z",
        )
        # group by week and month
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person6",
            timestamp="2019-11-05T16:30:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person7",
            timestamp="2019-11-07T16:50:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2019-11-27T16:50:00Z",
        )

        flush_persons_and_events()
        return person1, person2, person3, person4, person5, person6, person7

    def test_hour_interval(self):
        sign_up_action, person = self._create_events()

        (
            person1,
            person2,
            person3,
            person4,
            person5,
            person6,
            person7,
        ) = self._create_people_interval_events()

        _create_person(team_id=self.team.pk, distinct_ids=["outside_range"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-01-04T13:50:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-01-04T15:50:00Z",
        )
        # check solo hour
        action_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 14:00:00",
                "date_to": "2020-01-04 14:59:59",
                ENTITY_TYPE: "actions",
                ENTITY_ID: sign_up_action.id,
            },
        ).json()
        event_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 14:00:00",
                "date_to": "2020-01-04 14:59:59",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
            },
        ).json()
        self.assertEqual(str(action_response["results"][0]["people"][0]["id"]), str(person1.uuid))
        self.assertEqual(len(action_response["results"][0]["people"]), 1)
        self.assertEntityResponseEqual(action_response["results"], event_response["results"], remove=[])

        # check grouped hour
        hour_grouped_action_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 16:00:00",
                "date_to": "2020-01-04 16:59:59",
                ENTITY_TYPE: "actions",
                ENTITY_ID: sign_up_action.id,
            },
        ).json()
        hour_grouped_grevent_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 16:00:00",
                "date_to": "2020-01-04 16:59:59",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
            },
        ).json()
        all_people_ids = [str(person["id"]) for person in hour_grouped_action_response["results"][0]["people"]]
        self.assertListEqual(sorted(all_people_ids), sorted([str(person2.uuid), str(person3.uuid)]))
        self.assertEqual(len(all_people_ids), 2)
        self.assertEntityResponseEqual(
            hour_grouped_action_response["results"],
            hour_grouped_grevent_response["results"],
            remove=[],
        )

    def test_day_interval(self):
        sign_up_action, person = self._create_events()
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2020-01-04T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            timestamp="2020-01-05T12:00:00Z",
        )
        _create_person(team_id=self.team.pk, distinct_ids=["outside_range"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-01-03T13:50:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-01-05T15:50:00Z",
        )

        # test people
        action_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-04",
                "date_to": "2020-01-04 23:59:59",
                ENTITY_TYPE: "actions",
                "interval": "day",
                ENTITY_ID: sign_up_action.id,
            },
        ).json()
        event_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-04",
                "date_to": "2020-01-04 23:59:59",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
                "interval": "day",
            },
        ).json()

        self.assertEqual(len(action_response["results"][0]["people"]), 1)
        self.assertEqual(str(action_response["results"][0]["people"][0]["id"]), str(person1.uuid))
        self.assertEntityResponseEqual(action_response["results"], event_response["results"], remove=[])

    def test_day_interval_cumulative(self):
        sign_up_action, person = self._create_events()
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        person2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2020-01-03T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            timestamp="2020-01-04T20:00:00Z",
        )
        _create_person(team_id=self.team.pk, distinct_ids=["outside_range"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-01-02T13:50:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-01-05T15:50:00Z",
        )

        # test people
        action_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-03",
                "date_to": "2020-01-04 23:59:59",
                ENTITY_TYPE: "actions",
                "interval": "day",
                ENTITY_ID: sign_up_action.id,
                "display": TRENDS_CUMULATIVE,
            },
        ).json()
        event_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-03",
                "date_to": "2020-01-04 23:59:59",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
                "interval": "day",
                "display": TRENDS_CUMULATIVE,
            },
        ).json()
        self.assertEqual(len(action_response["results"][0]["people"]), 2)
        self.assertEqual(
            sorted(p["id"] for p in action_response["results"][0]["people"]),
            sorted([str(person1.uuid), str(person2.uuid)]),
        )
        self.assertEntityResponseEqual(action_response["results"], event_response["results"], remove=[])

    def test_week_interval(self):
        sign_up_action, person = self._create_events()

        (
            person1,
            person2,
            person3,
            person4,
            person5,
            person6,
            person7,
        ) = self._create_people_interval_events()

        _create_person(team_id=self.team.pk, distinct_ids=["outside_range"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2019-10-26T13:50:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-11-11T15:50:00Z",
        )
        # check grouped week
        week_grouped_action_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "week",
                "date_from": "2019-11-01",
                "date_to": "2019-11-07",
                ENTITY_TYPE: "actions",
                ENTITY_ID: sign_up_action.id,
            },
        ).json()
        week_grouped_grevent_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "week",
                "date_from": "2019-11-01",
                "date_to": "2019-11-07",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
            },
        ).json()

        self.maxDiff = None
        all_people_ids = [str(person["id"]) for person in week_grouped_action_response["results"][0]["people"]]
        self.assertEqual(len(all_people_ids), 2)
        self.assertListEqual(sorted(all_people_ids), sorted([str(person6.uuid), str(person7.uuid)]))

        self.assertEntityResponseEqual(
            week_grouped_action_response["results"],
            week_grouped_grevent_response["results"],
            remove=[],
        )

    def test_month_interval(self):
        sign_up_action, person = self._create_events()

        (
            person1,
            person2,
            person3,
            person4,
            person5,
            person6,
            person7,
        ) = self._create_people_interval_events()

        _create_person(team_id=self.team.pk, distinct_ids=["outside_range"])
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2019-12-01T13:50:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="outside_range",
            timestamp="2020-10-10T15:50:00Z",
        )
        # check grouped month
        month_group_action_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "month",
                "date_from": "2019-11-01",
                "date_to": "2019-11-30",
                ENTITY_TYPE: "actions",
                ENTITY_ID: sign_up_action.id,
            },
        ).json()
        month_group_grevent_response = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "interval": "month",
                "date_from": "2019-11-01",
                "date_to": "2019-11-30",
                ENTITY_TYPE: "events",
                ENTITY_ID: "sign up",
            },
        ).json()

        all_people_ids = [str(person["id"]) for person in month_group_action_response["results"][0]["people"]]
        self.assertEqual(len(all_people_ids), 3)
        self.assertListEqual(
            sorted(all_people_ids),
            sorted([str(person6.uuid), str(person7.uuid), str(person1.uuid)]),
        )

        self.assertEntityResponseEqual(
            month_group_action_response["results"],
            month_group_grevent_response["results"],
            remove=[],
        )

    def _create_multiple_people(self):
        person1 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"name": "person1"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
            properties={"event_prop": "prop1"},
        )

        person2 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"name": "person2"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-01T12:00:00Z",
            properties={"event_prop": "prop1"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"event_prop": "prop1"},
        )
        # same day
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"event_prop": "prop1"},
        )

        person3 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"name": "person3"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-01T12:00:00Z",
            properties={"event_prop": "prop2"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"event_prop": "prop2"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-03T12:00:00Z",
            properties={"event_prop": "prop2"},
        )

        person4 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["person4"],
            properties={"name": "person4"},
        )
        _create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person4",
            timestamp="2020-01-05T12:00:00Z",
            properties={"event_prop": "prop3"},
        )
        flush_persons_and_events()
        return (person1, person2, person3, person4)

    def test_breakdown_by_cohort_people_endpoint(self):
        person1, _, _, _ = self._create_multiple_people()
        cohort = _create_cohort(
            name="cohort1",
            team=self.team,
            groups=[{"properties": [{"key": "name", "value": "person1", "type": "person"}]}],
        )
        _create_cohort(name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}])
        _create_cohort(
            name="cohort3",
            team=self.team,
            groups=[
                {"properties": {"name": "person1"}},
                {"properties": {"name": "person2"}},
            ],
        )
        _create_action(name="watched movie", team=self.team)

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                "display": TRENDS_CUMULATIVE,  # ensure date range is used as is
                ENTITY_TYPE: "events",
                ENTITY_ID: "watched movie",
                "breakdown_type": "cohort",
                "breakdown_value": cohort.pk,
                "breakdown": [cohort.pk],  # this shouldn't do anything
            },
        ).json()

        self.assertEqual(len(people["results"][0]["people"]), 1)
        ordered_people = sorted(people["results"][0]["people"], key=lambda i: i["id"])
        self.assertEqual(ordered_people[0]["id"], str(person1.uuid))

        # all people
        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                "display": TRENDS_CUMULATIVE,  # ensure date range is used as is
                ENTITY_TYPE: "events",
                ENTITY_ID: "watched movie",
                "breakdown_type": "cohort",
                "breakdown_value": "all",
                "breakdown": [cohort.pk],
            },
        ).json()

        self.assertEqual(len(people["results"][0]["people"]), 4)
        ordered_people = sorted(people["results"][0]["people"], key=lambda i: i["created_at"])
        self.assertEqual(ordered_people[0]["id"], str(person1.uuid))

    def test_breakdown_by_person_property_people_endpoint(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        _create_action(name="watched movie", team=self.team)

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                ENTITY_TYPE: "events",
                ENTITY_ID: "watched movie",
                "properties": json.dumps([{"key": "name", "value": "person3", "type": "person"}]),
                "breakdown_type": "person",
                "breakdown_value": "person3",
                "breakdown": "name",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 1)
        self.assertEqual(people["results"][0]["people"][0]["id"], str(person3.uuid))

    def test_breakdown_by_event_property_people_endpoint(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        _create_action(name="watched movie", team=self.team)

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                ENTITY_TYPE: "events",
                ENTITY_ID: "watched movie",
                "properties": json.dumps([{"key": "event_prop", "value": "prop1", "type": "event"}]),
                "breakdown_type": "event",
                "breakdown_value": "prop1",
                "breakdown": "event_prop",
            },
        ).json()

        self.assertEqual(len(people["results"][0]["people"]), 2)
        ordered_people = sorted(p["id"] for p in people["results"][0]["people"])
        self.assertEqual(ordered_people, sorted([str(person1.uuid), str(person2.uuid)]))

    def test_filtering_by_person_properties(self):
        person1, person2, person3, person4 = self._create_multiple_people()

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                ENTITY_TYPE: "events",
                ENTITY_ID: "watched movie",
                "properties": json.dumps([{"key": "name", "value": "person2", "type": "person"}]),
            },
        ).json()

        self.assertEqual(len(people["results"][0]["people"]), 1)
        self.assertEqual(people["results"][0]["people"][0]["id"], str(person2.uuid))

    def test_active_user_weekly_people(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-10",
                "date_to": "2020-01-10",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                ENTITY_MATH: "weekly_active",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 2)

    def test_breakdown_by_person_property_nones_people_endpoint(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-10",
                "date_to": "2020-01-10",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                "breakdown_type": "person",
                "breakdown_value": "p1",
                "breakdown": "name",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 1)

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-10",
                "date_to": "2020-01-10",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                "breakdown_type": "person",
                "breakdown_value": "",
                "breakdown": "name",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 1)

    def test_breakdown_by_event_property_none_people_endpoint(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-8",
                "date_to": "2020-01-12",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                "display": TRENDS_CUMULATIVE,  # ensure that the date range is used as is
                "breakdown_type": "event",
                "breakdown_value": "val",
                "breakdown": "key",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 2)

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-08",
                "date_to": "2020-01-12",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                "display": TRENDS_CUMULATIVE,  # ensure that the date range is used as is
                "breakdown_type": "event",
                "breakdown_value": "",
                "breakdown": "key",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 1)

    @snapshot_clickhouse_queries
    def test_trends_people_endpoint_includes_recordings(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T14:00:00Z",
        )
        _create_event(
            event_uuid="693402ed-590e-4737-ba26-93ebf18121bd",
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"$session_id": "s1", "$window_id": "w1"},
        )
        timestamp = datetime(2020, 1, 9, 12)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="u1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        people = self.client.get(
            f"/api/projects/{self.team.id}/persons/trends/",
            data={
                "date_from": "2020-01-08",
                "date_to": "2020-01-12",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                "display": TRENDS_CUMULATIVE,
                "breakdown_type": "event",
                "breakdown_value": "",
                "breakdown": "key",
                "include_recordings": "true",
            },
        ).json()
        self.assertEqual(
            people["results"][0]["people"][0]["matched_recordings"],
            [
                {
                    "session_id": "s1",
                    "events": [
                        {
                            "window_id": "w1",
                            "timestamp": "2020-01-09T12:00:00Z",
                            "uuid": "693402ed-590e-4737-ba26-93ebf18121bd",
                        }
                    ],
                }
            ],
        )

    @snapshot_clickhouse_queries
    def test_trends_people_endpoint_filters_search(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"email": "ben@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T14:00:00Z",
        )

        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p2"],
            properties={"email": "neil@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T14:00:00Z",
        )

        params = {
            "date_from": "2020-01-08",
            "date_to": "2020-01-12",
            ENTITY_TYPE: "events",
            ENTITY_ID: "$pageview",
            "display": TRENDS_CUMULATIVE,
            "breakdown_type": "event",
            "breakdown_value": "",
            "breakdown": "key",
            "include_recordings": "true",
        }

        people = self.client.get(f"/api/projects/{self.team.id}/persons/trends/", data=params).json()
        assert len(people["results"][0]["people"]) == 2

        params["search"] = "ben"

        people = self.client.get(f"/api/projects/{self.team.id}/persons/trends/", data=params).json()
        assert len(people["results"][0]["people"]) == 1
