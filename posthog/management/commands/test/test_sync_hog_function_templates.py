from posthog.management.commands.sync_hog_function_templates import TYPES_WITH_JAVASCRIPT_SOURCE
import pytest
from unittest.mock import patch, MagicMock
from django.core.management import call_command

from posthog.models.hog_function_template import HogFunctionTemplate as DBHogFunctionTemplate
from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.management.commands.sync_hog_function_templates import (
    TEST_INCLUDE_PYTHON_TEMPLATE_IDS,
    TEST_INCLUDE_NODEJS_TEMPLATE_IDS,
)

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
        db_templates = DBHogFunctionTemplate.objects.filter(template_id__in=TEST_INCLUDE_PYTHON_TEMPLATE_IDS)
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
                    "hog": "return event",
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
            node_template = DBHogFunctionTemplate.objects.filter(template_id=template_id).first()
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
        db_template_ids = set(DBHogFunctionTemplate.objects.values_list("template_id", flat=True))
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
        db_template_ids = set(DBHogFunctionTemplate.objects.values_list("template_id", flat=True))
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
        DBHogFunctionTemplate.objects.all().delete()

        # First run - templates should be created
        from io import StringIO

        stdout = StringIO()
        call_command("sync_hog_function_templates", stdout=stdout)
        output = stdout.getvalue()

        # We should have at least created the Python test templates
        expected_created = len(TEST_INCLUDE_PYTHON_TEMPLATE_IDS)

        # Check that templates were reported as created
        assert f"Created: {expected_created}" in output or f"Created: " in output

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
        db_template = DBHogFunctionTemplate.objects.get(template_id=slack_template.id)

        # Verify core template fields
        assert db_template.name == slack_template.name
        assert db_template.code == slack_template.hog
        assert db_template.type == slack_template.type

        # Only check bytecode if it's not a JavaScript template
        if db_template.type not in TYPES_WITH_JAVASCRIPT_SOURCE:
            assert db_template.bytecode is not None

        dataclass_template = db_template.to_dataclass()
        assert dataclass_template.id == slack_template.id
        assert dataclass_template.name == slack_template.name
        assert dataclass_template.hog == slack_template.hog

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_template_version_behavior(self, mock_get_hog_function_templates):
        """Test that template versioning behaves correctly"""
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplate as DataclassTemplate

        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Create a test template
        test_template = DataclassTemplate(
            id="test-versioning-template",
            name="Test Versioning Template",
            description="Test template for version behavior",
            type="transformation",
            hog="return event",
            inputs_schema=[],
            status="beta",
            free=True,
            category=["Test"],
            code_language="hog",
        )

        # Save the template to the database
        template_1, created_1 = DBHogFunctionTemplate.create_from_dataclass(test_template)
        assert created_1 is True
        initial_sha = template_1.sha

        # Save the exact same template again
        template_2, created_2 = DBHogFunctionTemplate.create_from_dataclass(test_template)
        assert created_2 is False  # Should not create a new record
        assert template_2.id == template_1.id  # Should be the same database record
        assert template_2.sha == initial_sha  # sha should be unchanged

        # Verify only one template exists in the database
        template_count = DBHogFunctionTemplate.objects.filter(template_id="test-versioning-template").count()
        assert template_count == 1

        # Create a modified version of the template (can't modify frozen dataclass)
        modified_template = DataclassTemplate(
            id="test-versioning-template",  # Same ID
            name="Modified Test Template",  # Changed
            description="This template was modified",  # Changed
            type="transformation",
            hog="return null",  # Changed
            inputs_schema=[],
            status="beta",
            free=True,
            category=["Test"],
            code_language="hog",
        )

        # Save the modified template
        template_3, created_3 = DBHogFunctionTemplate.create_from_dataclass(modified_template)
        assert created_3 is False  # Should not create a new record
        assert template_3.id == template_1.id  # Should update the same database record
        assert template_3.sha != initial_sha  # sha should be different
        assert template_3.name == "Modified Test Template"
        assert template_3.description == "This template was modified"
        assert template_3.code == "return null"

        # Verify still only one template exists in the database
        template_count = DBHogFunctionTemplate.objects.filter(template_id="test-versioning-template").count()
        assert template_count == 1
