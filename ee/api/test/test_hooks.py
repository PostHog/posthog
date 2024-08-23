from typing import cast
from unittest.mock import ANY

from ee.api.hooks import valid_domain
from ee.api.test.base import APILicensedTest
from ee.models.hook import Hook
from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.test.base import ClickhouseTestMixin


class TestHooksAPI(ClickhouseTestMixin, APILicensedTest):
    action: Action

    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(
            team=self.team,
            name="Test Action",
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [],
                }
            ],
        )

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

    def test_delete_hook(self):
        hook_id = "abc123"
        Hook.objects.create(id=hook_id, user=self.user, team=self.team, resource_id=20)
        response = self.client.delete(f"/api/projects/{self.team.id}/hooks/{hook_id}")
        self.assertEqual(response.status_code, 204)

    def test_invalid_target(self):
        data = {
            "target": "https://hooks.non-zapier.com/abcd/",
            "event": "action_performed",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)
        self.assertEqual(response.status_code, 400)

    def test_create_hog_function_via_hook(self):
        data = {
            "target": "https://hooks.zapier.com/hooks/standard/1234/abcd",
            "event": "action_performed",
            "resource_id": self.action.id,
        }

        with self.settings(HOOK_HOG_FUNCTION_TEAMS="*"):
            res = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)

        assert res.status_code == 201, res.json()
        json = res.json()

        assert not Hook.objects.exists()
        assert HogFunction.objects.count() == 1
        hog_function = HogFunction.objects.first()
        assert hog_function
        assert json == {
            "id": str(hog_function.id),
            "event": "action_performed",
            "target": "https://hooks.zapier.com/hooks/standard/1234/abcd",
            "resource_id": self.action.id,
        }

        assert hog_function.filters == {
            "actions": [{"id": str(self.action.id), "name": "", "type": "actions", "order": 0}],
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11, 3, 1, 4, 1],
        }

        assert hog_function.inputs == {
            "body": {
                "bytecode": ANY,
                "value": {
                    "data": {
                        "distinctId": "{event.distinct_id}",
                        "event": "{event.name}",
                        "eventUuid": "{event.uuid}",
                        "person": {
                            "properties": "{person.properties}",
                            "uuid": "{person.uuid}",
                        },
                        "properties": "{event.properties}",
                        "teamId": "{project.id}",
                        "timestamp": "{event.timestamp}",
                    },
                    "hook": {
                        "event": "{event}",
                        "id": "{eventUuid}",
                        "target": "https://hooks.zapier.com/{inputs.hook}",
                    },
                },
            },
            "debug": {},
            "hook": {
                "bytecode": [
                    "_H",
                    1,
                    32,
                    "hooks/standard/1234/abcd",
                ],
                "value": "hooks/standard/1234/abcd",
            },
        }

    def test_delete_hog_function_via_hook(self):
        data = {
            "target": "https://hooks.zapier.com/hooks/standard/1234/abcd",
            "event": "action_performed",
            "resource_id": self.action.id,
        }

        with self.settings(HOOK_HOG_FUNCTION_TEAMS="*"):
            res = self.client.post(f"/api/projects/{self.team.id}/hooks/", data)

        hook_id = res.json()["id"]

        assert HogFunction.objects.count() == 1

        with self.settings(HOOK_HOG_FUNCTION_TEAMS="*"):
            res = self.client.delete(f"/api/projects/{self.team.id}/hooks/{hook_id}")
            assert res.status_code == 204

        assert not HogFunction.objects.exists()


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
