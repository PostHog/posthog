from posthog.test.base import APIBaseTest

from inline_snapshot import snapshot

from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models.hog_flow.hog_flow import HogFlow

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create slack template in DB
        sync_template_to_db(template_slack)
        sync_template_to_db(webhook_template)

    def _create_hog_flow_with_action(self, action_config: dict):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": action_config,
        }

        hog_flow = {
            "name": "Test Flow",
            "actions": [trigger_action, action],
        }

        return hog_flow, action

    def test_hog_flow_function_trigger_check(self):
        hog_flow = {
            "name": "Test Flow",
            "actions": [],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions",
            "code": "invalid_input",
            "detail": "Exactly one trigger action is required",
            "type": "validation_error",
        }

    def test_hog_flow_function_trigger_copied_from_action(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {"value": "https://example.com"},
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        trigger_action_expectation = {
            "id": "trigger_node",
            "name": "trigger_1",
            "description": "",
            "on_error": None,
            "filters": None,
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {
                        "value": "https://example.com",
                        "bytecode": ["_H", 1, 32, "https://example.com"],
                        "order": 0,
                    }
                },
            },
            "output_variable": None,
        }

        assert response.status_code == 201, response.json()
        assert response.json()["actions"] == [trigger_action_expectation]
        assert response.json()["trigger"] == trigger_action_expectation["config"]

    def test_hog_flow_function_validation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "missing",
                "inputs": {},
            }
        )

        # Check that the template is found but missing required inputs
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__template_id",
            "code": "invalid_input",
            "detail": "Template not found",
            "type": "validation_error",
        }

        # Check that the template is found but missing required inputs
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__inputs__url",
            "code": "invalid_input",
            "detail": "This field is required.",
            "type": "validation_error",
        }

    def test_hog_flow_bytecode_compilation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        action["filters"] = {
            "events": [{"id": "custom_event", "name": "custom_event", "type": "events", "order": 0}],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        hog_flow = HogFlow.objects.get(pk=response.json()["id"])

        assert hog_flow.trigger["filters"].get("bytecode") == snapshot(
            ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]
        )

        assert hog_flow.actions[1]["filters"].get("bytecode") == snapshot(
            ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]
        )

        assert hog_flow.actions[1]["config"]["inputs"] == snapshot(
            {"url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}}
        )

    def test_hog_flow_enable_disable(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        assert response.json()["status"] == "draft"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{response.json()['id']}", {"status": "active"}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "active"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{response.json()['id']}", {"status": "draft"}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "draft"
