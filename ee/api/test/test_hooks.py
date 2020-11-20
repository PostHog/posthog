from typing import Type

from ee.api.test.base import APITransactionLicensedTest
from ee.models.hook import Hook


class TestHooksAPI(APITransactionLicensedTest):
    TESTS_API = True

    def test_create_hook(self):
        data = {"target": "https://hooks.example.com/abcd/", "event": "annotation_created"}
        with self.settings(DEBUG=1):
            response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        self.assertEqual(response.status_code, 201)
        hook: Type[Hook] = Hook.objects.first()
        self.assertEqual(hook.team, self.team)
        self.assertEqual(hook.target, data["target"])
        self.assertEqual(hook.event, data["event"])
        self.assertEqual(hook.resource_id, None)
        self.assertEqual(response.data["id"], hook.id)
        self.assertEqual(response.data["event"], data["event"])
        self.assertEqual(response.data["target"], data["target"])
        self.assertEqual(response.data["resource_id"], None)
        self.assertEqual(response.data["team"], self.team.id)

    def test_create_hook_with_resource_id(self):
        data = {"target": "https://hooks.example.com/abcd/", "event": "annotation_created", "resource_id": "66"}
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        self.assertEqual(response.status_code, 201)
        hook: Type[Hook] = Hook.objects.first()
        self.assertEqual(hook.team, self.team)
        self.assertEqual(hook.target, data["target"])
        self.assertEqual(hook.event, data["event"])
        self.assertEqual(str(hook.resource_id), data["resource_id"])
        self.assertEqual(response.data["id"], hook.id)
        self.assertEqual(response.data["event"], data["event"])
        self.assertEqual(response.data["target"], data["target"])
        self.assertEqual(str(response.data["resource_id"]), data["resource_id"])
        self.assertEqual(response.data["team"], self.team.id)
