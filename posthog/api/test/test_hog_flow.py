from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.test.base import APIBaseTest


class TestHogFlowAPI(APIBaseTest):
    def test_hog_flow_bytecode_compilation(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Test Flow",
                "trigger": {
                    "type": "webhook",
                    "filters": {},
                },
                "actions": {
                    "action_1": {
                        "hasCompiledConfigInputs": True,
                        "config": {"inputs": {"key": "value"}},
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        hog_flow = HogFlow.objects.get(pk=response.json()["id"])
        self.assertIn("bytecode", hog_flow.actions["action_1"]["config"]["inputs"])

        # Test that the bytecode is generated correctly
        self.assertListEqual(
            hog_flow.actions["action_1"]["config"]["inputs"]["bytecode"]["key"],
            ["_H", 1, 32, "value"],
        )

    def test_hog_flow_bytecode_compilation_on_update(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Test Flow",
                "trigger": {
                    "type": "webhook",
                    "filters": {},
                },
                "actions": {
                    "action_1": {
                        "hasCompiledConfigInputs": True,
                        "config": {"inputs": {"key": "value"}},
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        hog_flow = HogFlow.objects.get(pk=response.json()["id"])
        self.assertListEqual(
            hog_flow.actions["action_1"]["config"]["inputs"]["bytecode"]["key"],
            ["_H", 1, 32, "value"],
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{hog_flow.id}",
            {
                "actions": {
                    "action_1": {
                        "hasCompiledConfigInputs": True,
                        "config": {"inputs": {"key": "new_value"}},
                    }
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        hog_flow = HogFlow.objects.get(pk=response.json()["id"])
        self.assertIn("bytecode", hog_flow.actions["action_1"]["config"]["inputs"])

        # Test that the bytecode is generated correctly
        self.assertListEqual(
            hog_flow.actions["action_1"]["config"]["inputs"]["bytecode"]["key"],
            ["_H", 1, 32, "new_value"],
        )
