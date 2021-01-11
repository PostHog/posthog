from typing import Type, cast
from unittest.mock import Mock, patch
from uuid import uuid4

from ee.api.test.base import APITransactionLicensedTest
from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from ee.models.hook import Hook
from posthog.models import Action, ActionStep
from posthog.models.event import Event


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


class TestHooksAPI(ClickhouseTestMixin, APITransactionLicensedTest):
    TESTS_API = True

    def test_create_hook(self):
        data = {"target": "https://hooks.example.com/abcd/", "event": "annotation_created"}
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        self.assertEqual(response.status_code, 201)
        hook: Type[Hook] = Hook.objects.first()
        self.assertEqual(hook.team, self.team)
        self.assertEqual(hook.target, data["target"])
        self.assertEqual(hook.event, data["event"])
        self.assertEqual(hook.resource_id, None)
        self.assertDictContainsSubset(
            {
                "id": hook.id,
                "event": data["event"],
                "target": data["target"],
                "resource_id": None,
                "team": self.team.id,
            },
            cast(dict, response.data),
        )

    def test_create_hook_with_resource_id(self):
        data = {"target": "https://hooks.example.com/abcd/", "event": "annotation_created", "resource_id": "66"}
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        self.assertEqual(response.status_code, 201)
        hook: Type[Hook] = Hook.objects.first()
        self.assertEqual(hook.team, self.team)
        self.assertEqual(hook.target, data["target"])
        self.assertEqual(hook.event, data["event"])
        self.assertEqual(str(hook.resource_id), data["resource_id"])
        self.assertDictContainsSubset(
            {
                "id": hook.id,
                "event": data["event"],
                "target": data["target"],
                "resource_id": int(data["resource_id"]),
                "team": self.team.id,
            },
            cast(dict, response.data),
        )

    def test_delete_hook(self):
        hook_id = "abc123"
        Hook.objects.create(id=hook_id, user=self.user, team=self.team, resource_id=20)
        response = self.client.delete(f"/api/projects/{self.team.id}/hooks/{hook_id}")
        self.assertEqual(response.status_code, 204)

    @patch("ee.models.hook.find_and_fire_hook")
    @patch("ee.models.hook.deliver_hook_wrapper")
    def test_action_on_perform_hook_fired_once(self, mock_deliver_hook_wrapper: Mock, mock_find_and_fire_hook: Mock):
        hook_id = "abc123"
        Hook.objects.create(id=hook_id, user=self.user, team=self.team, resource_id=8)
        action = Action.objects.create("anything")
        ActionStep.objects.create(action=action)
        _create_event(event="asdfghjkl", team=self.team, distinct_id="whatever")
        mock_find_and_fire_hook.assert_called_once()
        mock_deliver_hook_wrapper.assert_called_once()
