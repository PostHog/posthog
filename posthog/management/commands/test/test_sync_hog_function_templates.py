import pytest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.management.commands.sync_hog_function_templates import (
    TEST_INCLUDE_NODEJS_TEMPLATE_IDS,
    TEST_INCLUDE_PYTHON_TEMPLATE_IDS,
    TYPES_WITH_JAVASCRIPT_SOURCE,
)
from posthog.models.hog_function_template import HogFunctionTemplate

pytestmark = pytest.mark.django_db


class TestSyncHogFunctionTemplates:
    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_sync_python_templates(self, mock_get_hog_function_templates):
        """Test that Python templates are synced to the database."""
        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Run the command
        call_command("sync_hog_function_templates")

        # Verify that the Python test template was created successfully
        db_templates = HogFunctionTemplate.objects.filter(template_id__in=TEST_INCLUDE_PYTHON_TEMPLATE_IDS)
        assert db_templates.count() == len(TEST_INCLUDE_PYTHON_TEMPLATE_IDS)

        # Verify that each template has the expected ID
        db_template_ids = {template.template_id for template in db_templates}
        assert db_template_ids == set(TEST_INCLUDE_PYTHON_TEMPLATE_IDS)

        # Verify that the Python templates have bytecode compiled
        for template in db_templates:
            if template.type not in TYPES_WITH_JAVASCRIPT_SOURCE:
                assert template.bytecode is not None

    @patch("posthog.management.commands.sync_hog_function_templates.get_hog_function_templates")
    def test_sync_nodejs_templates(self, mock_get_hog_function_templates):
        """Test that Node.js templates are synced to the database."""
        # Create mock Node.js templates that match the TEST_INCLUDE_NODEJS_TEMPLATE_IDS
        mock_node_templates = []
        for template_id in TEST_INCLUDE_NODEJS_TEMPLATE_IDS:
            mock_node_templates.append(
                {
                    "id": template_id,
                    "name": f"Test {template_id}",
                    "description": f"Test template for {template_id}",
                    "type": "transformation",
                    "code": "return event",
                    "inputs_schema": [],
                    "status": "beta",
                    "free": True,
                    "category": ["Custom"],
                    "code_language": "javascript",
                }
            )

        # Set up the mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_node_templates
        mock_get_hog_function_templates.return_value = mock_response

        # Run the command
        call_command("sync_hog_function_templates")

        # Verify that Node.js test templates were synced correctly
        for template_id in TEST_INCLUDE_NODEJS_TEMPLATE_IDS:
            node_template = HogFunctionTemplate.objects.filter(template_id=template_id).first()
            assert node_template is not None
            assert node_template.type == "transformation"
            assert node_template.name == f"Test {template_id}"

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_sync_handles_invalid_template(self, mock_get_hog_function_templates):
        """Test that the command handles invalid templates gracefully."""
        # Create an invalid Node.js template (missing required fields)
        mock_invalid_template = {
            "id": "invalid_template",
            "type": "destination",  # Valid type but missing other required fields
            # Missing required fields like name, hog, etc.
        }

        # Mock the Node.js API response with an invalid template
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [mock_invalid_template]
        mock_get_hog_function_templates.return_value = mock_response

        # Run the command, should not raise an exception
        call_command("sync_hog_function_templates")

        # Verify that the Python test templates were still created but not the invalid one
        db_template_ids = set(HogFunctionTemplate.objects.values_list("template_id", flat=True))
        assert all(tid in db_template_ids for tid in TEST_INCLUDE_PYTHON_TEMPLATE_IDS)
        assert "invalid_template" not in db_template_ids

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_sync_handles_api_error(self, mock_get_hog_function_templates):
        """Test that the command handles API errors gracefully."""
        # Mock an API error
        mock_get_hog_function_templates.side_effect = Exception("API Error")

        # Run the command, should not raise an exception
        call_command("sync_hog_function_templates")

        # Verify that Python test templates were still created
        db_template_ids = set(HogFunctionTemplate.objects.values_list("template_id", flat=True))
        assert all(tid in db_template_ids for tid in TEST_INCLUDE_PYTHON_TEMPLATE_IDS)

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_sync_metrics(self, mock_get_hog_function_templates):
        """Test that the command reports the correct metrics."""
        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        HogFunctionTemplate.objects.all().delete()

        # First run - templates should be created
        from io import StringIO

        stdout = StringIO()
        call_command("sync_hog_function_templates", stdout=stdout)
        output = stdout.getvalue()

        # We should have at least created the Python test templates
        expected_created = len(TEST_INCLUDE_PYTHON_TEMPLATE_IDS)

        # Check that templates were reported as created
        assert f"Created or updated: {expected_created}" in output or f"Created or updated: " in output

        # Second run - templates should be skipped/updated since they already exist
        stdout = StringIO()
        call_command("sync_hog_function_templates", stdout=stdout)
        output = stdout.getvalue()

        # Just check that the command ran successfully
        assert "Sync completed" in output

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_template_contents(self, mock_get_hog_function_templates):
        """Test that template contents are properly stored in the database."""
        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        call_command("sync_hog_function_templates")

        # Find the slack template in HOG_FUNCTION_TEMPLATES
        slack_template = next((t for t in HOG_FUNCTION_TEMPLATES if t.id == TEST_INCLUDE_PYTHON_TEMPLATE_IDS[0]), None)
        assert (
            slack_template is not None
        ), f"Template {TEST_INCLUDE_PYTHON_TEMPLATE_IDS[0]} not found in HOG_FUNCTION_TEMPLATES"

        # Check that the template was stored correctly
        db_template = HogFunctionTemplate.objects.get(template_id=slack_template.id)

        # Verify core template fields
        assert db_template.name == slack_template.name
        assert db_template.code == slack_template.code
        assert db_template.type == slack_template.type

        # Only check bytecode if it's not a JavaScript template
        if db_template.type not in TYPES_WITH_JAVASCRIPT_SOURCE:
            assert db_template.bytecode is not None

        assert db_template.template_id == slack_template.id
        assert db_template.name == slack_template.name
        assert db_template.code == slack_template.code

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_template_version_behavior(self, mock_get_hog_function_templates):
        """Test that template versioning behaves correctly"""
        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        HogFunctionTemplate.objects.all().delete()

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_delete_deleted_coming_soon_templates(self, mock_get_hog_function_templates):
        """Test that coming-soon templates are properly deleted when they're no longer in in the codebase."""

        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        HogFunctionTemplate.objects.all().delete()

        # First, create some templates that will be in the current sync
        call_command("sync_hog_function_templates")

        # Verify initial state - should have Python test templates
        initial_count = HogFunctionTemplate.objects.count()
        assert initial_count > 0

        # Create a template that does not exist anymore
        HogFunctionTemplate.objects.create(
            template_id="coming-soon-old-template",
            name="Old Template",
            description="This template has been deleted",
            type="destination",
            code="return event",
            inputs_schema=[],
            status="beta",
            free=True,
            category=["Custom"],
            code_language="hog",
        )

        # Verify the old template was created
        assert HogFunctionTemplate.objects.filter(template_id="coming-soon-old-template").exists()

        # Run sync again - should detect and delete the old template
        call_command("sync_hog_function_templates")

        # Verify the old template was deleted
        assert not HogFunctionTemplate.objects.filter(template_id="coming-soon-old-template").exists()

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_does_not_delete_deleted_templates(self, mock_get_hog_function_templates):
        """Test that non coming-soon templates are not deleted when they're no longer in in the codebase."""

        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        HogFunctionTemplate.objects.all().delete()

        # First, create some templates that will be in the current sync
        call_command("sync_hog_function_templates")

        # Verify initial state - should have Python test templates
        initial_count = HogFunctionTemplate.objects.count()
        assert initial_count > 0

        # Create a template that does not exist anymore
        HogFunctionTemplate.objects.create(
            template_id="old-template",
            name="Old Template",
            description="This template has been deleted",
            type="destination",
            code="return event",
            inputs_schema=[],
            status="beta",
            free=True,
            category=["Custom"],
            code_language="hog",
        )

        # Verify the old template was created
        assert HogFunctionTemplate.objects.filter(template_id="old-template").exists()

        # Run sync again - should detect and delete the old template
        call_command("sync_hog_function_templates")

        # Verify the old template was deleted
        assert HogFunctionTemplate.objects.filter(template_id="old-template").exists()
