from unittest.mock import patch
from uuid import uuid4

from rest_framework import status

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_action import factory_test_action_api
from posthog.api.test.test_action_people import action_people_test_factory
from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE
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
    @patch("posthog.tasks.calculate_action.calculate_action.delay")
    def test_is_calculating_always_false(self, patch_delay):
        create_response_wrapper = self.client.post("/api/action/", {"name": "ooh"})
        create_response = create_response_wrapper.json()
        self.assertEqual(create_response_wrapper.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response["is_calculating"], False)
        self.assertFalse(patch_delay.called)

        response = self.client.get("/api/action/").json()
        self.assertEqual(response["results"][0]["is_calculating"], False)

        response = self.client.get("/api/action/%s/" % create_response["id"]).json()
        self.assertEqual(response["is_calculating"], False)

        # Make sure we're not re-calculating actions
        response = self.client.patch("/api/action/%s/" % create_response["id"], {"name": "ooh"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "ooh")
        self.assertEqual(response.json()["is_calculating"], False)
        self.assertFalse(patch_delay.called)

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
            "/api/action/people/",
            data={
                "date_from": "2020-01-10",
                "date_to": "2020-01-10",
                ENTITY_TYPE: "events",
                ENTITY_ID: "$pageview",
                ENTITY_MATH: "weekly_active",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 2)
