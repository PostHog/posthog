from typing import Type, cast

from ee.api.hooks import valid_domain
from ee.api.test.base import APILicensedTest
from ee.clickhouse.util import ClickhouseTestMixin
from ee.models.hook import Hook


class TestHooksAPI(ClickhouseTestMixin, APILicensedTest):
    def test_create_hook(self):
        data = {"target": "https://hooks.zapier.com/abcd/", "event": "annotation_created"}
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
            cast(dict, response.json()),
        )

    def test_create_hook_with_resource_id(self):
        data = {"target": "https://hooks.zapier.com/abcd/", "event": "annotation_created", "resource_id": "66"}
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
            cast(dict, response.json()),
        )

    def test_delete_hook(self):
        hook_id = "abc123"
        Hook.objects.create(id=hook_id, user=self.user, team=self.team, resource_id=20)
        response = self.client.delete(f"/api/projects/{self.team.id}/hooks/{hook_id}")
        self.assertEqual(response.status_code, 204)

    def test_invalid_target(self):
        data = {"target": "https://hooks.non-zapier.com/abcd/", "event": "annotation_created"}
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        self.assertEqual(response.status_code, 400)


def test_valid_domain() -> None:

    test_cases = {
        "http://hooks.zapier.com": True,
        "https://hooks.zapier.com": True,
        "http://hooks.zapier.com/something": True,
        "https://hooks.zapier.com/something": True,
        "http://hooks.zapierz.com": False,
        "https://hooks.zapierz.com": False,
        "http://hoos.zapier.com/something": False,
        "https://hoos.zapier.com/something": False,
    }

    for test_input, expected_test_output in test_cases.items():
        test_output = valid_domain(test_input)
        assert test_output == expected_test_output
