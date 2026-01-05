import json
from io import BytesIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import Client, override_settings

from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate


class TestWorkflowTemplateImportExportAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)
        self.user.is_staff = True
        self.user.save()

    def _create_valid_template_data(self):
        """Helper to create valid template data for import"""
        return {
            "name": "Test Template",
            "description": "Test description",
            "scope": "global",
            "trigger": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                    "source": "events",
                    "actions": [],
                    "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
                },
            },
            "actions": [
                {
                    "id": "trigger_node",
                    "name": "Trigger",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "filters": {
                            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                            "source": "events",
                            "actions": [],
                            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
                        },
                    },
                    "filters": None,
                    "on_error": None,
                    "created_at": 0,
                    "updated_at": 0,
                    "description": "User performs an action to start the workflow.",
                    "output_variable": None,
                },
                {
                    "id": "exit_node",
                    "name": "Exit",
                    "type": "exit",
                    "config": {"reason": "Default exit"},
                    "filters": None,
                    "on_error": None,
                    "created_at": 0,
                    "updated_at": 0,
                    "description": "User moved through the workflow without errors.",
                    "output_variable": None,
                },
            ],
            "edges": [
                {"to": "exit_node", "from": "trigger_node", "type": "continue"},
            ],
            "abort_action": None,
            "variables": [],
        }

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    @patch("posthog.admin.admins.workflow_template_import_export_admin._get_team_id_from_domain")
    def test_valid_import_succeeds(self, mock_get_team_id):
        """Test that importing valid template data succeeds"""
        mock_get_team_id.return_value = self.team.id

        template_data = self._create_valid_template_data()
        json_content = json.dumps([template_data]).encode("utf-8")
        json_file = BytesIO(json_content)
        json_file.name = "test_templates.json"

        response = self.client.post(
            "/admin/workflow-template-import-export/",
            {"json_file": json_file},
        )

        # Should redirect on success
        assert response.status_code == 302

        # Verify template was created
        template = HogFlowTemplate.objects.filter(name="Test Template", scope=HogFlowTemplate.Scope.GLOBAL).first()
        assert template is not None
        assert template.name == "Test Template"
        assert template.scope == HogFlowTemplate.Scope.GLOBAL

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    @patch("posthog.admin.admins.workflow_template_import_export_admin._get_team_id_from_domain")
    def test_invalid_json_fails(self, mock_get_team_id):
        """Test that importing invalid JSON fails"""
        mock_get_team_id.return_value = self.team.id

        invalid_json = b"not valid json"
        json_file = BytesIO(invalid_json)
        json_file.name = "test_templates.json"

        response = self.client.post(
            "/admin/workflow-template-import-export/",
            {"json_file": json_file},
        )

        # Should redirect with error message
        assert response.status_code == 302

        # Follow redirect to check for error message
        response = self.client.get("/admin/workflow-template-import-export/")
        assert b"Error parsing JSON" in response.content or b"Invalid JSON" in response.content

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    @patch("posthog.admin.admins.workflow_template_import_export_admin._get_team_id_from_domain")
    def test_invalid_template_data_fails(self, mock_get_team_id):
        """Test that importing invalid template data fails"""
        mock_get_team_id.return_value = self.team.id

        invalid_template = {
            "name": "Invalid Template",
            "scope": "global",
            # Missing required fields like actions, trigger
        }
        json_content = json.dumps([invalid_template]).encode("utf-8")
        json_file = BytesIO(json_content)
        json_file.name = "test_templates.json"

        response = self.client.post(
            "/admin/workflow-template-import-export/",
            {"json_file": json_file},
        )

        # Should redirect (errors are shown via messages)
        assert response.status_code == 302

        # Verify template was NOT created
        template = HogFlowTemplate.objects.filter(name="Invalid Template").first()
        assert template is None

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    @patch("posthog.admin.admins.workflow_template_import_export_admin._get_team_id_from_domain")
    def test_non_global_template_is_filtered_out(self, mock_get_team_id):
        """Test that non-global templates are filtered out during import"""
        mock_get_team_id.return_value = self.team.id

        template_data = self._create_valid_template_data()
        template_data["scope"] = "team"  # Not global
        json_content = json.dumps([template_data]).encode("utf-8")
        json_file = BytesIO(json_content)
        json_file.name = "test_templates.json"

        response = self.client.post(
            "/admin/workflow-template-import-export/",
            {"json_file": json_file},
        )

        # Should redirect
        assert response.status_code == 302

        # Verify template was NOT created (filtered out)
        template = HogFlowTemplate.objects.filter(name="Test Template").first()
        assert template is None

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    @patch("posthog.admin.admins.workflow_template_import_export_admin._get_team_id_from_domain")
    def test_import_with_same_id_overwrites_existing_template(self, mock_get_team_id):
        """Test that importing a template with the same ID overwrites the existing template"""
        mock_get_team_id.return_value = self.team.id

        # Create an existing template
        existing_template = HogFlowTemplate.objects.create(
            id="019b6f44-f9a3-0000-c4a7-b8050d25d690",
            name="Original Template",
            description="Original description",
            scope=HogFlowTemplate.Scope.GLOBAL,
            team=self.team,
            trigger={"type": "event", "filters": {}},
            actions=[
                {
                    "id": "trigger_node",
                    "name": "Trigger",
                    "type": "trigger",
                    "config": {"type": "event", "filters": {}},
                }
            ],
            created_by=self.user,
        )

        # Import a new template with the same ID but different data
        template_data = self._create_valid_template_data()
        template_data["id"] = "019b6f44-f9a3-0000-c4a7-b8050d25d690"
        template_data["name"] = "Updated Template"
        template_data["description"] = "Updated description"
        json_content = json.dumps([template_data]).encode("utf-8")
        json_file = BytesIO(json_content)
        json_file.name = "test_templates.json"

        response = self.client.post(
            "/admin/workflow-template-import-export/",
            {"json_file": json_file},
        )

        # Should redirect on success
        assert response.status_code == 302

        # Verify only one template exists with this ID
        templates = HogFlowTemplate.objects.filter(id="019b6f44-f9a3-0000-c4a7-b8050d25d690")
        assert templates.count() == 1

        # Verify the template was updated (not duplicated)
        existing_template.refresh_from_db()
        assert existing_template.name == "Updated Template"
        assert existing_template.description == "Updated description"
        assert existing_template.scope == HogFlowTemplate.Scope.GLOBAL

    def test_non_staff_user_denied(self):
        """Test that non-staff users cannot access the admin view"""
        self.user.is_staff = False
        self.user.save()

        response = self.client.get("/admin/workflow-template-import-export/")

        assert response.status_code == 403
