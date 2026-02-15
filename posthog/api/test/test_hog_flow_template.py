from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Team
from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate
from posthog.models.hog_function_template import HogFunctionTemplate

from products.workflows.backend.templates import clear_template_cache, load_global_templates

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowTemplateAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

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
        """Test that scope field can be set to team but not global (global templates are code-only)"""
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "team"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.scope == "team"

        # Even staff users cannot create global templates in the database
        self.user.is_staff = True
        self.user.save()
        hog_flow_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 403
        assert "global workflow templates are stored in code" in response.json()["detail"].lower()

    def test_template_image_url_field(self):
        """Test that image_url field can be set"""
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["image_url"] = "https://example.com/image.png"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.image_url == "https://example.com/image.png"

    def test_template_tags_field(self):
        """Test that tags field can be set, updated, and defaults to empty list"""
        hog_flow_data = self._create_hog_flow_data()
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()
        assert response.json()["tags"] == []
        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.tags == []

        hog_flow_data["tags"] = ["ingestion", "batch"]
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201, response.json()
        assert response.json()["tags"] == ["ingestion", "batch"]

        template = HogFlowTemplate.objects.get(pk=response.json()["id"])
        assert template.tags == ["ingestion", "batch"]

        template_id = response.json()["id"]
        update_data = self._create_hog_flow_data()
        update_data["tags"] = ["updated-tag"]
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 200
        assert response.json()["tags"] == ["updated-tag"]
        template.refresh_from_db()
        assert template.tags == ["updated-tag"]

    def test_template_filtering_returns_global_and_team_templates(self):
        """Test that listing templates returns file-based global templates and team templates from DB"""
        team_template_data = self._create_hog_flow_data()
        team_template_data["scope"] = "team"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", team_template_data)
        assert response.status_code == 201
        team_template_id = response.json()["id"]

        # Load file-based global templates
        clear_template_cache()
        file_templates = load_global_templates()
        assert len(file_templates) > 0, "No global templates loaded from files"
        file_template_id = file_templates[0]["id"]

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

        # Should include team template and file-based global templates
        assert team_template_id in template_ids
        assert file_template_id in template_ids

        # Should not include other team's templates
        assert str(other_team_template.id) not in template_ids

    def test_template_filtering_global_templates_visible_to_all_teams(self):
        """Test that file-based global templates are visible to all teams"""
        clear_template_cache()
        file_templates = load_global_templates()
        assert len(file_templates) > 0, "No global templates loaded from files"
        global_template_id = file_templates[0]["id"]

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

    def test_cannot_create_global_template_in_database(self):
        """Test that users cannot create global templates in the database (they must be in code)"""
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "global"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 403
        assert "global workflow templates are stored in code" in response.json()["detail"].lower()

    def test_cannot_update_team_template_to_global_scope(self):
        """Test that users cannot update a team template to global scope"""
        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "team"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 201
        template_id = response.json()["id"]

        update_data = self._create_hog_flow_data()
        update_data["scope"] = "global"
        update_data["name"] = "Updated Name"

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 403
        assert "global workflow templates are stored in code" in response.json()["detail"].lower()

    def test_updating_team_template_to_global_is_blocked(self):
        """Test that updating a team template to global scope is blocked"""
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
        assert "global workflow templates are stored in code" in response.json()["detail"].lower()

        template.refresh_from_db()
        assert template.scope == "team"
        assert template.name != "Updated Name"  # Update should have failed completely

    def test_staff_cannot_create_global_templates_in_database(self):
        """Test that even staff users cannot create global templates in database (must use code files)"""
        self.user.is_staff = True
        self.user.save()

        hog_flow_data = self._create_hog_flow_data()
        hog_flow_data["scope"] = "global"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_templates", hog_flow_data)
        assert response.status_code == 403
        assert "global workflow templates are stored in code" in response.json()["detail"].lower()

    def test_public_list_flow_templates(self):
        """Test that the public endpoint returns global templates from files"""
        clear_template_cache()

        # Log out to test unauthenticated access
        self.client.logout()
        response = self.client.get("/api/public_hog_flow_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()

        # Should return file-based templates
        results = response.json()["results"]
        assert len(results) > 0, "No templates returned from public endpoint"

        # All returned templates should have scope='global'
        for template in results:
            assert template["scope"] == "global", f"Public endpoint returned non-global template: {template['id']}"

    def test_loads_templates_from_template_files(self):
        """Test that the API loads global templates from products/workflows/backend/templates/*.template.py"""
        # Clear cache to ensure we load fresh
        clear_template_cache()

        file_templates = load_global_templates()

        assert len(file_templates) > 0, "No templates loaded from template files"

        file_template_ids = {t["id"] for t in file_templates}
        file_template_names = {t["name"] for t in file_templates}

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_templates")
        assert response.status_code == 200

        api_results = response.json()["results"]
        api_template_ids = {t["id"] for t in api_results}
        api_template_names = {t["name"] for t in api_results}

        # All file-based templates should be present in API response
        for template_id in file_template_ids:
            assert template_id in api_template_ids, f"Template {template_id} from files not found in API response"

        for template_name in file_template_names:
            assert template_name in api_template_names, (
                f"Template '{template_name}' from files not found in API response"
            )

        # Verify that file templates have scope='global'
        for template in api_results:
            if template["id"] in file_template_ids:
                assert template["scope"] == "global", f"Template {template['id']} from files should have scope='global'"

    def test_can_retrieve_individual_template_from_files(self):
        """Test that we can retrieve a specific template that's loaded from files"""
        clear_template_cache()
        file_templates = load_global_templates()

        assert len(file_templates) > 0, "No templates loaded from template files"

        # Get the first template ID
        template_id = file_templates[0]["id"]
        template_name = file_templates[0]["name"]

        # Retrieve it via the API
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}")
        assert response.status_code == 200, f"Failed to retrieve template {template_id}"

        retrieved = response.json()
        assert retrieved["id"] == template_id
        assert retrieved["name"] == template_name
        assert retrieved["scope"] == "global"

    def test_file_based_global_templates_not_accessible_via_write_endpoints(self):
        """Test that file-based global templates return 404 on update/delete (not in DB queryset)"""
        clear_template_cache()
        file_templates = load_global_templates()

        assert len(file_templates) > 0, "No templates loaded from template files"

        template_id = file_templates[0]["id"]

        # Try to update - returns 404 because file-based templates aren't in the DB queryset
        update_data = {"name": "Updated Template Name", "description": "Updated description"}

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}", update_data)
        assert response.status_code == 404

        # Try to delete - also returns 404 for the same reason
        response = self.client.delete(f"/api/projects/{self.team.id}/hog_flow_templates/{template_id}")
        assert response.status_code == 404
