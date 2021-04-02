from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_event import factory_test_event_api
from posthog.models import Action, ActionStep, Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def _create_person(**kwargs):
    return Person.objects.create(**kwargs)


class ClickhouseTestEventApi(
    ClickhouseTestMixin, factory_test_event_api(_create_event, _create_person, _create_action)  # type: ignore
):
    def test_live_action_events(self):
        pass

    @patch("ee.clickhouse.views.events.sync_execute")
    def test_optimize_query(self, patch_sync_execute):
        #  For ClickHouse we normally only query the last day,
        # but if a user doesn't have many events we still want to return events that are older
        patch_sync_execute.return_value = [("event", "d", "{}", timezone.now(), "d", "d", "d")]
        response = self.client.get("/api/event/").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(patch_sync_execute.call_count, 2)

        patch_sync_execute.return_value = [("event", "d", "{}", timezone.now(), "d", "d", "d") for _ in range(0, 100)]
        response = self.client.get("/api/event/").json()
        self.assertEqual(patch_sync_execute.call_count, 3)
