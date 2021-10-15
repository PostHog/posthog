from unittest.mock import patch
from uuid import uuid4

from rest_framework import status

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_action import factory_test_action_api
from posthog.api.test.test_action_people import action_people_test_factory
from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE, TRENDS_CUMULATIVE
from posthog.models import Action, ActionStep, Cohort, Organization, Person


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    return cohort


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=str(person.uuid))


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestActionApi(ClickhouseTestMixin, factory_test_action_api(_create_event)):  # type: ignore
    pass


class TestActionPeople(
    ClickhouseTestMixin, action_people_test_factory(_create_event, _create_person, _create_action, _create_cohort)  # type: ignore
):
    @patch("posthog.models.action.Action.calculate_events")
    def test_is_calculating_always_false(self, calculate_events):
        create_response_wrapper = self.client.post(f"/api/projects/{self.team.id}/actions/", {"name": "ooh"})
        create_response = create_response_wrapper.json()
        self.assertEqual(create_response_wrapper.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response["is_calculating"], False)
        self.assertFalse(calculate_events.called)

        response = self.client.get(f"/api/projects/{self.team.id}/actions/").json()
        self.assertEqual(response["results"][0]["is_calculating"], False)

        response = self.client.get(f"/api/projects/{self.team.id}/actions/{create_response['id']}/").json()
        self.assertEqual(response["is_calculating"], False)

        # Make sure we're not re-calculating actions
        response = self.client.patch(f"/api/projects/{self.team.id}/actions/{create_response['id']}/", {"name": "ooh"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "ooh")
        self.assertEqual(response.json()["is_calculating"], False)
        self.assertFalse(calculate_events.called)

    def test_active_user_weekly_people(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
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

        p2 = _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
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
            f"/api/projects/{self.team.id}/actions/people/",
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
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
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

        p2 = _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={})
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
            f"/api/projects/{self.team.id}/actions/people/",
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
            f"/api/projects/{self.team.id}/actions/people/",
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
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
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

        p2 = _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z", properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        people = self.client.get(
            f"/api/projects/{self.team.id}/actions/people/",
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
            f"/api/projects/{self.team.id}/actions/people/",
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

    def _test_interval(self, date_from, interval, timestamps):
        for index, ts in enumerate(timestamps):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{index}"])
            _create_event(
                team=self.team,
                event="watched movie",
                distinct_id=f"person{index}",
                timestamp=ts,
                properties={"event_prop": f"prop{index}"},
            )

        people = self.client.get(
            f"/api/projects/{self.team.id}/actions/people/",
            data={"interval": interval, "date_from": date_from, ENTITY_TYPE: "events", ENTITY_ID: "watched movie"},
        ).json()

        self.assertCountEqual(
            [person["distinct_ids"][0] for person in people["results"][0]["people"]], ["person1", "person2"]
        )

    def test_interval_month(self):
        self._test_interval(
            date_from="2021-08-01T00:00:00Z",
            interval="month",
            timestamps=[
                "2021-07-31T23:45:00Z",
                "2021-08-01T00:12:00Z",
                "2021-08-31T22:40:00Z",
                "2021-09-01T00:00:10Z",
            ],
        )

    def test_interval_week(self):
        self._test_interval(
            date_from="2021-09-05T00:00:00Z",
            interval="week",
            timestamps=[
                "2021-09-04T23:45:00Z",
                "2021-09-05T00:12:00Z",
                "2021-09-11T22:40:00Z",
                "2021-09-12T00:00:10Z",
            ],
        )

    def test_interval_day(self):
        self._test_interval(
            date_from="2021-09-05T00:00:00Z",
            interval="day",
            timestamps=[
                "2021-09-04T23:45:00Z",
                "2021-09-05T00:12:00Z",
                "2021-09-05T22:40:00Z",
                "2021-09-06T00:00:10Z",
            ],
        )

    def test_interval_hour(self):
        self._test_interval(
            date_from="2021-09-05T16:00:00Z",
            interval="hour",
            timestamps=[
                "2021-09-05T15:45:00Z",
                "2021-09-05T16:01:12Z",
                "2021-09-05T16:58:00Z",
                "2021-09-05T17:00:10Z",
            ],
        )

    def test_interval_minute(self):
        self._test_interval(
            date_from="2021-09-05T16:05:00Z",
            interval="minute",
            timestamps=[
                "2021-09-05T16:04:55Z",
                "2021-09-05T16:05:12Z",
                "2021-09-05T16:05:58Z",
                "2021-09-05T16:06:10Z",
            ],
        )
