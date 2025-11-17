from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models.hog_functions.hog_function import HogFunction


class TestUpdateHogFunctionCode(BaseTest):
    def setUp(self):
        super().setUp()

        # Create HogFunctions for testing
        with patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            # LinkedIn destination with old API version
            self.linkedin_function1 = HogFunction.objects.create(
                team=self.team,
                name="LinkedIn Function 1",
                type="destination",
                template_id="template-linkedin-ads",
                description="Test LinkedIn Function 1",
                hog="const headers = {'LinkedIn-Version': '202409'}; return event;",
                enabled=True,
            )

            # LinkedIn destination with new API version (should not be updated)
            self.linkedin_function2 = HogFunction.objects.create(
                team=self.team,
                name="LinkedIn Function 2",
                type="destination",
                template_id="template-linkedin-ads",
                description="Test LinkedIn Function 2",
                hog="const headers = {'LinkedIn-Version': '202508'}; return event;",
                enabled=True,
            )

            # Non-LinkedIn destination (should not be processed)
            self.other_function = HogFunction.objects.create(
                team=self.team,
                name="Other Function",
                type="destination",
                template_id="template-other",
                description="Test Other Function",
                hog="const headers = {'LinkedIn-Version': '202409'}; return event;",
                enabled=True,
            )

            # Deleted function (should not be processed)
            self.deleted_function = HogFunction.objects.create(
                team=self.team,
                name="Deleted Function",
                type="destination",
                template_id="template-linkedin-ads",
                description="Test Deleted Function",
                hog="const headers = {'LinkedIn-Version': '202409'}; return event;",
                enabled=True,
                deleted=True,
            )

    @patch("posthog.management.commands.update_hog_function_code.compile_hog")
    def test_update_linkedin_api_version_dry_run(self, mock_compile_hog):
        """Test dry run mode - should show what would be updated without making changes."""
        mock_compile_hog.return_value = "compiled_bytecode"

        out = StringIO()
        call_command("update_hog_function_code", replace_key="linked-api-version-update", dry_run=True, stdout=out)

        # Should have compiled but not saved anything
        assert mock_compile_hog.call_count == 1

        # Check that no functions were actually updated
        self.linkedin_function1.refresh_from_db()
        assert "'LinkedIn-Version': '202409'" in self.linkedin_function1.hog

        output = out.getvalue()
        self.assertIn("DRY RUN - No changes will be made", output)
        self.assertIn("Found 2 destinations to process", output)
        self.assertIn("Updated: 1", output)
        self.assertIn("Update completed", output)

    @patch("posthog.management.commands.update_hog_function_code.compile_hog")
    def test_update_linkedin_api_version_actual_update(self, mock_compile_hog):
        """Test actual update - should update LinkedIn functions with old API version."""
        mock_compile_hog.return_value = "compiled_bytecode"

        out = StringIO()
        call_command("update_hog_function_code", replace_key="linked-api-version-update", stdout=out)

        # Should have compiled and saved the functions that needed updating
        assert mock_compile_hog.call_count == 1

        # Check that functions were actually updated
        self.linkedin_function1.refresh_from_db()
        assert "'LinkedIn-Version': '202508'" in self.linkedin_function1.hog

        # Check that functions that didn't need updating weren't changed
        self.linkedin_function2.refresh_from_db()
        assert "'LinkedIn-Version': '202409'" not in self.linkedin_function2.hog
        assert "'LinkedIn-Version': '202508'" in self.linkedin_function2.hog

        output = out.getvalue()
        self.assertIn("Found 2 destinations to process", output)
        self.assertIn("Updated: 1", output)
        self.assertIn("Update completed", output)

    @patch("posthog.cdp.validation.compile_hog")
    def test_invalid_replace_key(self, mock_compile_hog):
        """Test handling of invalid replace key."""
        out = StringIO()
        call_command("update_hog_function_code", replace_key="invalid-key", stdout=out)

        # Should not have compiled anything
        assert mock_compile_hog.call_count == 0

        output = out.getvalue()
        self.assertIn("Invalid replace key provided: invalid-key", output)

    def test_missing_replace_key(self):
        """Test handling of missing replace key."""
        out = StringIO()
        call_command("update_hog_function_code", stdout=out)

        output = out.getvalue()
        self.assertIn("Invalid replace key provided: None", output)

    @patch("posthog.cdp.validation.compile_hog")
    def test_no_matching_functions(self, mock_compile_hog):
        """Test when no functions match the criteria."""
        # Delete all LinkedIn functions
        HogFunction.objects.filter(template_id="template-linkedin-ads").delete()

        out = StringIO()
        call_command("update_hog_function_code", replace_key="linked-api-version-update", stdout=out)

        # Should not have compiled anything
        assert mock_compile_hog.call_count == 0

        output = out.getvalue()
        self.assertIn("Found 0 destinations to process", output)
        self.assertIn("Updated: 0", output)
