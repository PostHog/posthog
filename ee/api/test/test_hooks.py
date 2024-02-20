from typing import cast

from ee.api.test.base import APILicensedTest
from ee.models.hook import Hook
from posthog.test.base import ClickhouseTestMixin


class TestHooksAPI(ClickhouseTestMixin, APILicensedTest):
    def _create_hook(self, target="https://example.com/hook/", event="action_performed", resource_id=1):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hooks/", {"target": target, "event": event, "resource_id": resource_id}
        )
        assert response.status_code == 201
        return response.json()

    def test_create_hook(self):
        data = {"target": "https://hooks.zapier.com/abcd/", "event": "action_performed"}
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        response_data = response.json()

        hook = Hook.objects.get(id=response_data["id"])
        self.assertEqual(response.status_code, 201)
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
            cast(dict, response.json()),
        )

    def test_create_hook_with_resource_id(self):
        data = {
            "target": "https://hooks.zapier.com/abcd/",
            "event": "action_performed",
            "resource_id": "66",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        response_data = response.json()

        hook = Hook.objects.get(id=response_data["id"])
        self.assertEqual(response.status_code, 201)
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
            cast(dict, response.json()),
        )

    def test_validates_url(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hooks/",
            {
                "target": "NOT_A_URL",
                "event": "action_performed",
                "resource_id": "66",
            },
        )
        assert response.status_code == 400, response.json()
        assert response.json()["detail"] == "Enter a valid URL."

    def test_delete_hook(self):
        hook_id = "abc123"
        Hook.objects.create(id=hook_id, user=self.user, team=self.team, resource_id=20)
        response = self.client.delete(f"/api/projects/{self.team.id}/hooks/{hook_id}")
        self.assertEqual(response.status_code, 204)

    def test_list_hooks(self):
        self._create_hook(resource_id=1)
        self._create_hook(resource_id=1)
        self._create_hook(resource_id=2)
        response = self.client.get(f"/api/projects/{self.team.id}/hooks/")
        self.assertEqual(len(response.json()["results"]), 3)

        response = self.client.get(f"/api/projects/{self.team.id}/hooks/?resource_id=1")
        self.assertEqual(len(response.json()["results"]), 2)
