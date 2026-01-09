from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Team
from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate
from posthog.models.hog_function_template import HogFunctionTemplate

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowTemplateAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.feature_flag_patcher = patch("posthog.api.hog_flow_template.posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.mock_feature_enabled.return_value = True

        # Create slack template in DB
        sync_template_to_db(template_slack)
        sync_template_to_db(webhook_template)

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

    def tearDown(self):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()
        super().tearDown()

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
            "scope": "team",
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

    def test_template_creation(self):
        """Test that templates are created with correct function actions"""
        hog_flow_data = self._create_hog_flow_data(custom_inputs={"url": {"value": "https://custom.example.com"}})

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        function_action = next(action for action in template.actions if action["type"] == "function")

        # Verify inputs are preserved - only url was provided in custom_inputs
        assert function_action["config"]["inputs"] == {"url": {"value": "https://custom.example.com"}}

    def test_template_creation_with_multiple_function_actions(self):
        """Test that all function actions preserve their inputs when creating templates"""
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
            "scope": "team",
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])

        function_actions = [action for action in template.actions if action["type"] == "function"]
        assert len(function_actions) == 2

        assert function_actions[0]["config"]["inputs"] == {"url": {"value": "https://custom1.example.com"}}
        assert function_actions[1]["config"]["inputs"] == {"url": {"value": "https://custom2.example.com"}}

    def test_template_creation_sets_team_and_created_by(self):
        """Test that team_id and created_by are set from context"""
        hog_flow_data = self._create_hog_flow_data()

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])

        assert template.team_id == self.team.id
        assert template.created_by == self.user

    def test_template_function_validation(self):
        """Test that function actions validate template_id exists"""
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
            "config": {
                "template_id": "missing",
                "inputs": {},
            },
        }

        hog_flow_data = {
            "name": "Test Flow",
            "actions": [trigger_action, action],
            "scope": "team",
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__template_id",
            "code": "invalid_input",
            "detail": "Template not found",
            "type": "validation_error",
        }

    def test_template_scope_field(self):
        """Test that scope field can be set to team or global"""
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "team"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.scope == "team"

        self.user.is_staff = True
        self.user.save()
        hog_flow_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.scope == "global"

    def test_template_image_url_field(self):
        """Test that image_url field can be set"""
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["image_url"] = "https://example.com/image.png"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.image_url == "https://example.com/image.png"

    def test_template_filtering_returns_global_and_team_templates(self):
        """Test that listing templates returns global templates and templates for current team"""
        team_template_data = self._create_hog_flow_data()
        team_template_data["scope"] = "team"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", team_template_data)
        assert response.status_code == 201
        team_template_id = response.json()["id"]

        self.user.is_staff = True
        self.user.save()
        global_template_data = self._create_hog_flow_data()
        global_template_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", global_template_data)
        assert response.status_code == 201
        global_template_id = response.json()["id"]

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_team_template = HogFlowTemplate.objects.create(
            name="Other Team Template",
            team=other_team,
            scope="team",
            trigger={"type": "event"},
            actions=[],
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_templates")
        assert response.status_code == 200

        template_ids = [t["id"] for t in response.json()["results"]]

        assert team_template_id in template_ids
        assert global_template_id in template_ids

        assert str(other_team_template.id) not in template_ids

    def test_template_filtering_global_templates_visible_to_all_teams(self):
        """Test that global templates are visible to all teams"""
        self.user.is_staff = True
        self.user.save()
        global_template_data = self._create_hog_flow_data()
        global_template_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", global_template_data)
        assert response.status_code == 201
        global_template_id = response.json()["id"]

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        response = self.client.get(f"/api/projects/{other_team.id}/hog_flow_templates")
        assert response.status_code == 200

        template_ids = [t["id"] for t in response.json()["results"]]
        assert global_template_id in template_ids

    def test_cannot_read_other_team_template(self):
        """Test that users cannot read team templates from other teams"""
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_team_template = HogFlowTemplate.objects.create(
            name="Other Team Template",
            team=other_team,
            scope="team",
            trigger={"type": "event"},
            actions=[],
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_templates/{other_team_template.id}")
        assert response.status_code == 404

    def test_cannot_update_other_team_template(self):
        """Test that users cannot update team templates from other teams"""
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_team_template = HogFlowTemplate.objects.create(
            name="Other Team Template",
            team=other_team,
            scope="team",
            trigger={"type": "event"},
            actions=[],
            created_by=self.user,
        )

        update_data = self._create_hog_flow_data()
        update_data["name"] = "Updated Name"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flow_templates/{other_team_template.id}", update_data
        )
        assert response.status_code == 404

    def test_cannot_delete_other_team_template(self):
        """Test that users cannot delete team templates from other teams"""
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_team_template = HogFlowTemplate.objects.create(
            name="Other Team Template",
            team=other_team,
            scope="team",
            trigger={"type": "event"},
            actions=[],
            created_by=self.user,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/hog_flow_templates/{other_team_template.id}")
        assert response.status_code == 404

        assert HogFlowTemplate.objects.filter(id=other_team_template.id).exists()

    def test_can_read_update_delete_own_team_template(self):
        """Test that users can read, update, and delete their own team templates"""
        template_data = self._create_hog_flow_data()
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", template_data)
        assert response.status_code == 201
        template_id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}")
        assert response.status_code == 200
        assert response.json()["id"] == template_id

        update_data = self._create_hog_flow_data()
        update_data["name"] = "Updated Template Name"
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Template Name"

        response = self.client.delete(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}")
        assert response.status_code == 204

        assert not HogFlowTemplate.objects.filter(id=template_id).exists()

    def test_cannot_create_global_template_without_staff(self):
        """Test that non-staff users cannot create global templates"""
        self.user.is_staff = False
        self.user.save()

        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "global"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 403
        assert "you don't have edit permissions for global workflow templates" in response.json()["detail"].lower()

    def test_cannot_update_global_template_without_staff(self):
        """Test that non-staff users cannot update global templates"""
        self.user.is_staff = True
        self.user.save()
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201
        template_id = response.json()["id"]

        self.user.is_staff = False
        self.user.save()
        update_data = self._create_hog_flow_data()
        update_data["scope"] = "global"
        update_data["name"] = "Updated Name"

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 403
        assert "you don't have edit permissions for global workflow templates" in response.json()["detail"].lower()

    def test_cannot_delete_global_template_without_staff(self):
        """Test that non-staff users cannot delete global templates"""

        self.user.is_staff = True
        self.user.save()
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201
        template_id = response.json()["id"]

        self.user.is_staff = False
        self.user.save()
        response = self.client.delete(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}")
        assert response.status_code == 403
        assert "you don't have edit permissions for global workflow templates" in response.json()["detail"].lower()

        assert HogFlowTemplate.objects.filter(id=template_id).exists()

    def test_cannot_update_team_template_to_global_without_staff(self):
        """Test that non-staff users cannot update a team template to global scope"""
        self.user.is_staff = False
        self.user.save()

        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "team"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201
        template_id = response.json()["id"]

        template = HogFlowTemplate.objects.get(id=template_id)
        assert template.scope == "team"

        update_data = self._create_hog_flow_data()
        update_data["scope"] = "global"
        update_data["name"] = "Updated Name"

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 403
        assert "you don't have edit permissions for global workflow templates" in response.json()["detail"].lower()

        template.refresh_from_db()
        assert template.scope == "team"
        assert template.name != "Updated Name"  # Update should have failed completely

    def test_can_create_update_delete_global_template_with_staff(self):
        """Test that staff users can create, update, and delete global templates"""
        self.user.is_staff = True
        self.user.save()

        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201
        template_id = response.json()["id"]

        update_data = self._create_hog_flow_data()
        update_data["scope"] = "global"
        update_data["name"] = "Updated Global Template"
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Global Template"

        response = self.client.delete(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}")
        assert response.status_code == 204

        assert not HogFlowTemplate.objects.filter(id=template_id).exists()
