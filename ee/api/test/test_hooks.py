import json
from datetime import datetime
from typing import Type

from ee.models import Hook
from posthog.api.test.base import BaseTest


class TestHooksAPI(BaseTest):
    TESTS_API = True

    def test_create_hook(self):
        data = {"target": "https://hooks.example.com/abcd/", "event": "annotation_created"}
        response = self.client.post("/api/hooks/", data).json()
        hook: Type[Hook] = Hook.objects.first()
        self.assertEqual(hook.team, self.team)
        self.assertEqual(hook.target, data["target"])
        self.assertEqual(hook.event, data["event"])
        self.assertEqual(hook.resource_id, None)
        self.assertEqual(response["id"], hook.id)
        self.assertEqual(response["event"], data["event"])
        self.assertEqual(response["target"], data["target"])
        self.assertEqual(response["resource_id"], None)
        self.assertEqual(response["team"], self.team.id)

    def test_create_hook_with_resource_id(self):
        data = {"target": "https://hooks.example.com/abcd/", "event": "annotation_created", "resource_id": "66"}
        response = self.client.post("/api/hooks/", data).json()
        hook: Type[Hook] = Hook.objects.first()
        self.assertEqual(hook.team, self.team)
        self.assertEqual(hook.target, data["target"])
        self.assertEqual(hook.event, data["event"])
        self.assertEqual(hook.resource_id, int(data["resource_id"]))
        self.assertEqual(response["id"], hook.id)
        self.assertEqual(response["event"], data["event"])
        self.assertEqual(response["target"], data["target"])
        self.assertEqual(response["resource_id"], int(data["resource_id"]))
        self.assertEqual(response["team"], self.team.id)
