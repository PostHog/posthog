from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.test.base import APIBaseTest
from inline_snapshot import snapshot

from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.api.test.test_hog_function import _create_template_from_mock
from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create slack template in DB
        HogFunctionTemplate.create_from_dataclass(template_slack)
        _create_template_from_mock(webhook_template)

        # # Mock the API call to get templates
        # with patch("posthog.api.hog_function_template.get_hog_function_templates") as mock_get_templates:
        #     mock_get_templates.return_value.status_code = 200
        #     mock_get_templates.return_value.json.return_value = MOCK_NODE_TEMPLATES
        #     HogFunctionTemplates._load_templates()  # Cache templates to simplify tests

    def _create_hog_flow_with_action(self, action_config: dict):
        action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": action_config,
        }

        hog_flow = {
            "name": "Test Flow",
            "trigger": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
            "actions": [action],
        }

        return hog_flow, action

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
            "attr": "actions__0__template_id",
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
            "attr": "actions__0__inputs__url",
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
            ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11, 3, 1, 4, 1]
        )

        assert hog_flow.actions[0]["filters"].get("bytecode") == snapshot(
            ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11, 3, 1, 4, 1]
        )

        assert hog_flow.actions[0]["config"]["inputs"] == snapshot(
            {"url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}}
        )
