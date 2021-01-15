from unittest.mock import patch
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_action_people import action_people_test_factory
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


class TestAction(
    ClickhouseTestMixin, action_people_test_factory(_create_event, _create_person, _create_action, _create_cohort)  # type: ignore
):
    @patch("posthog.tasks.calculate_action.calculate_action.delay")
    def test_is_calculating_always_false(self, patch_delay):
        create = self.client.post("/api/action/", data={"name": "ooh",}, content_type="application/json",).json()
        self.assertEqual(create["is_calculating"], False)
        self.assertFalse(patch_delay.called)

        response = self.client.get("/api/action/").json()
        self.assertEqual(response["results"][0]["is_calculating"], False)

        response = self.client.get("/api/action/%s/" % create["id"]).json()
        self.assertEqual(response["is_calculating"], False)

        # Make sure we're not re-calculating actions
        response = self.client.patch(
            "/api/action/%s/" % create["id"], data={"name": "ooh",}, content_type="application/json",
        ).json()
        self.assertEqual(response["name"], "ooh")
        self.assertEqual(response["is_calculating"], False)
        self.assertFalse(patch_delay.called)

    def test_only_get_count_on_retrieve(self):
        team2 = Organization.objects.bootstrap(None, team_fields={"name": "bla"})[2]
        action = Action.objects.create(team=self.team, name="bla")
        ActionStep.objects.create(action=action, event="custom event")
        _create_event(event="custom event", team=self.team, distinct_id="test")
        _create_event(event="another event", team=self.team, distinct_id="test")
        # test team leakage
        _create_event(event="custom event", team=team2, distinct_id="test")
        response = self.client.get("/api/action/").json()
        self.assertEqual(response["results"][0]["count"], None)

        response = self.client.get("/api/action/%s/" % action.pk).json()
        self.assertEqual(response["count"], 1)
