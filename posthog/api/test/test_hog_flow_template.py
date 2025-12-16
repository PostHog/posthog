from posthog.test.base import APIBaseTest

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate
from posthog.models.hog_function_template import HogFunctionTemplate


class TestHogFlowTemplateAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create slack template in DB
        sync_template_to_db(template_slack)

        # Create a template with default inputs for testing
        self.template_with_defaults = HogFunctionTemplate.objects.create(
            template_id="template-test-defaults",
            sha="1.0.0",
            name="Test Template With Defaults",
            description="Template with default inputs",
            code="return event",
            code_language="hog",
            inputs_schema=[
                {
                    "key": "url",
                    "type": "string",
                    "label": "URL",
                    "required": True,
                    "default": "https://default.example.com",
                },
                {
                    "key": "method",
                    "type": "string",
                    "label": "Method",
                    "required": False,
                    "default": "POST",
                },
                {
                    "key": "headers",
                    "type": "json",
                    "label": "Headers",
                    "required": False,
                    "default": {"Content-Type": "application/json"},
                },
            ],
            type="destination",
            status="stable",
            category=["Testing"],
            free=True,
        )

    def _create_hog_flow_data(self, include_metadata=False, custom_inputs=None):
        """Helper to create hog flow data for template creation"""
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

        function_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {
                "template_id": "template-test-defaults",
                "inputs": custom_inputs
                if custom_inputs is not None
                else {
                    "url": {"value": "https://custom.example.com"},
                    "method": {"value": "GET"},
                },
            },
        }

        hog_flow_data = {
            "name": "Test Template Flow",
            "description": "Test description",
            "actions": [trigger_action, function_action],
        }

        if include_metadata:
            hog_flow_data.update(
                {
                    "id": "should-be-removed-id",
                    "team_id": 99999,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-02T00:00:00Z",
                    "status": "active",
                }
            )

        return hog_flow_data

    def test_template_creation_removes_metadata_fields(self):
        """Test that metadata fields (id, team_id, created_at, updated_at, status) are removed"""
        hog_flow_data = self._create_hog_flow_data(include_metadata=True)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])

        # Verify metadata fields are not in the saved template
        assert template.id != "should-be-removed-id"
        assert template.team_id == self.team.id  # Should be set from context, not from data

        # Verify response doesn't include the removed fields
        response_data = response.json()
        assert response_data["id"] != "should-be-removed-id"
        assert "team_id" not in response_data
        assert "status" not in response_data  # Templates don't have status field

    def test_template_creation_resets_function_inputs_to_defaults(self):
        """Test that function action inputs are reset to template defaults"""
        hog_flow_data = self._create_hog_flow_data(custom_inputs={"url": {"value": "https://custom.example.com"}})

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        function_action = next(action for action in template.actions if action["type"] == "function")

        # Verify inputs were reset to defaults
        assert function_action["config"]["inputs"] == {
            "url": {"value": "https://default.example.com"},
            "method": {"value": "POST"},
            "headers": {"value": {"Content-Type": "application/json"}},
        }

    def test_template_creation_derives_trigger_from_actions(self):
        """Test that trigger is derived from trigger action config"""
        hog_flow_data = self._create_hog_flow_data()

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])

        # Verify trigger was derived from the trigger action
        trigger_action = next(action for action in template.actions if action["type"] == "trigger")
        assert template.trigger == trigger_action["config"]

    def test_template_creation_validates_actions(self):
        """Test that actions are validated before saving"""
        # Test missing trigger action
        hog_flow_data = {
            "name": "Test Flow",
            "actions": [
                {
                    "id": "action_1",
                    "name": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": "template-test-defaults",
                        "inputs": {},
                    },
                }
            ],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions",
            "code": "invalid_input",
            "detail": "Exactly one trigger action is required",
            "type": "validation_error",
        }

        # Test invalid template_id
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["actions"][1]["config"]["template_id"] = "missing-template"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__template_id",
            "code": "invalid_input",
            "detail": "Template not found",
            "type": "validation_error",
        }

    def test_template_creation_with_multiple_function_actions(self):
        """Test that all function actions have their inputs reset to defaults"""
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

        function_action_1 = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {
                "template_id": "template-test-defaults",
                "inputs": {"url": {"value": "https://custom1.example.com"}},
            },
        }

        function_action_2 = {
            "id": "action_2",
            "name": "action_2",
            "type": "function",
            "config": {
                "template_id": "template-test-defaults",
                "inputs": {"url": {"value": "https://custom2.example.com"}},
            },
        }

        hog_flow_data = {
            "name": "Test Template Flow",
            "actions": [trigger_action, function_action_1, function_action_2],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])

        # Verify both function actions have default inputs
        function_actions = [action for action in template.actions if action["type"] == "function"]
        assert len(function_actions) == 2

        for action in function_actions:
            assert action["config"]["inputs"] == {
                "url": {"value": "https://default.example.com"},
                "method": {"value": "POST"},
                "headers": {"value": {"Content-Type": "application/json"}},
            }

    def test_template_creation_with_trigger_function(self):
        """Test that trigger functions also have inputs reset to defaults"""
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook-defaults",
                "inputs": {"url": {"value": "https://custom-webhook.example.com"}},
            },
        }

        hog_flow_data = {
            "name": "Test Template Flow",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        trigger_action_saved = template.actions[0]

        # Verify trigger function inputs were reset to defaults
        assert trigger_action_saved["config"]["inputs"] == {"url": {"value": "https://webhook-default.example.com"}}

    def test_template_creation_sets_team_and_created_by(self):
        """Test that team_id and created_by are set from context"""
        hog_flow_data = self._create_hog_flow_data()

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])

        # Verify team_id and created_by are set correctly
        assert template.team_id == self.team.id
        assert template.created_by == self.user
