import pytest
from unittest.mock import patch, MagicMock
from django.core.management import call_command

from posthog.models.hog_function_template import HogFunctionTemplate as DBHogFunctionTemplate
from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES

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

        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Run the command
        call_command("sync_hog_function_templates")

        # Verify that templates with correct types were created
        db_template_ids = set(DBHogFunctionTemplate.objects.values_list("template_id", flat=True))

        # Get only Python templates with type 'transformation' or 'destination'
        valid_python_templates = [
            template for template in HOG_FUNCTION_TEMPLATES if template.type in ["transformation", "destination"]
        ]
        valid_python_template_ids = {template.id for template in valid_python_templates}

        assert len(db_template_ids) == len(valid_python_template_ids)
        assert db_template_ids == valid_python_template_ids

        # Verify that the templates have bytecode compiled
        for template in DBHogFunctionTemplate.objects.all():
            assert template.bytecode is not None
            # Verify it's one of the allowed types
            assert template.type in ["transformation", "destination"]

    @patch("posthog.management.commands.sync_hog_function_templates.get_hog_function_templates")
    def test_sync_nodejs_templates(self, mock_get_hog_function_templates):
        """Test that Node.js templates are synced to the database."""
        # Create a simple mock Node.js template
        mock_node_template = {
            "id": "template-geoip",
            "name": "GeoIP",
            "description": "Adds geoip data to the event",
            "type": "transformation",
            "hog": "return event",
            "inputs_schema": [],
            "status": "beta",
            "free": True,
            "category": ["Custom"],
        }

        # Set up the mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [mock_node_template]
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Run the command
        call_command("sync_hog_function_templates")

        # Verify that Node.js transformation templates are synced correctly
        geoip_template = DBHogFunctionTemplate.objects.filter(template_id="template-geoip").first()
        assert geoip_template is not None
        assert geoip_template.type == "transformation"
        assert geoip_template.name == "GeoIP"

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

        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Run the command, should not raise an exception
        call_command("sync_hog_function_templates")

        # Verify that valid Python templates were still created, but not the invalid one
        db_template_ids = set(DBHogFunctionTemplate.objects.values_list("template_id", flat=True))
        valid_python_templates = [
            template for template in HOG_FUNCTION_TEMPLATES if template.type in ["transformation", "destination"]
        ]
        valid_python_template_ids = {template.id for template in valid_python_templates}

        assert "invalid_template" not in db_template_ids
        assert db_template_ids == valid_python_template_ids

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_sync_handles_api_error(self, mock_get_hog_function_templates):
        """Test that the command handles API errors gracefully."""
        # Mock an API error
        mock_get_hog_function_templates.side_effect = Exception("API Error")

        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Run the command, should not raise an exception
        call_command("sync_hog_function_templates")

        # Verify that valid Python templates were still created
        db_template_ids = set(DBHogFunctionTemplate.objects.values_list("template_id", flat=True))
        valid_python_templates = [
            template for template in HOG_FUNCTION_TEMPLATES if template.type in ["transformation", "destination"]
        ]
        valid_python_template_ids = {template.id for template in valid_python_templates}

        assert len(db_template_ids) == len(valid_python_template_ids)
        assert db_template_ids == valid_python_template_ids

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

        # Count valid templates
        valid_python_templates = [
            template for template in HOG_FUNCTION_TEMPLATES if template.type in ["transformation", "destination"]
        ]
        valid_python_template_count = len(valid_python_templates)

        # First run - templates should be created
        from io import StringIO

        stdout = StringIO()
        call_command("sync_hog_function_templates", stdout=stdout)
        output = stdout.getvalue()

        # Check that templates were reported as created
        assert f"Created: {valid_python_template_count}" in output
        assert "Updated: 0" in output

        # Second run - templates should be skipped/updated since they already exist
        stdout = StringIO()
        call_command("sync_hog_function_templates", stdout=stdout)
        output = stdout.getvalue()

        # Checking exact counts is difficult because it depends on how content versioning works
        # So we just check that the command ran successfully
        assert "Sync completed" in output
        assert f"Templates: {valid_python_template_count}" in output

    @patch("posthog.plugins.plugin_server_api.get_hog_function_templates")
    def test_template_contents(self, mock_get_hog_function_templates):
        """Test that template contents are properly stored in the database."""
        # Mock the Node.js API to avoid external dependencies
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get_hog_function_templates.return_value = mock_response

        # Clear any existing templates
        DBHogFunctionTemplate.objects.all().delete()

        # Run the command
        call_command("sync_hog_function_templates")

        # Check that valid Python templates were stored correctly
        for template in HOG_FUNCTION_TEMPLATES:
            if template.type not in ["transformation", "destination"]:
                # Skip templates that should be filtered out
                continue

            db_template = DBHogFunctionTemplate.objects.get(template_id=template.id)

            # Verify core template fields
            assert db_template.name == template.name
            assert db_template.code == template.hog
            assert db_template.type == template.type
            assert db_template.bytecode is not None  # Bytecode should be compiled

            # Convert DB template back to dataclass and compare
            dataclass_template = db_template.to_dataclass()
            assert dataclass_template.id == template.id
            assert dataclass_template.name == template.name
            assert dataclass_template.hog == template.hog

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
