from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestUpdateHogFunctionCode(BaseTest):
    def setUp(self):
        super().setUp()

        # Create HogFunctions for testing
        with patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
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

            # Meta Ads destination with old API version
            self.meta_ads_function1 = HogFunction.objects.create(
                team=self.team,
                name="Meta Ads Function 1",
                type="destination",
                template_id="template-meta-ads",
                description="Test Meta Ads Function 1",
                hog="let res := fetch(f'https://graph.facebook.com/v21.0/{inputs.pixelId}/events', {}); return event;",
                enabled=True,
            )

            # Meta Ads destination with new API version (should not be updated)
            self.meta_ads_function2 = HogFunction.objects.create(
                team=self.team,
                name="Meta Ads Function 2",
                type="destination",
                template_id="template-meta-ads",
                description="Test Meta Ads Function 2",
                hog="let res := fetch(f'https://graph.facebook.com/v25.0/{inputs.pixelId}/events', {}); return event;",
                enabled=True,
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
        assert "DRY RUN - No changes will be made" in output
        assert "Found 2 destinations to process" in output
        assert "Updated: 1" in output
        assert "Update completed" in output

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
        assert "Found 2 destinations to process" in output
        assert "Updated: 1" in output
        assert "Update completed" in output

    @patch("posthog.management.commands.update_hog_function_code.compile_hog")
    def test_update_meta_ads_api_version_actual_update(self, mock_compile_hog):
        """Test actual update - should update Meta Ads functions with old API version."""
        mock_compile_hog.return_value = "compiled_bytecode"

        out = StringIO()
        call_command("update_hog_function_code", replace_key="meta-ads-api-version-update", stdout=out)

        # Should have compiled and saved only the function that needed updating
        assert mock_compile_hog.call_count == 1

        # Check that the function with the old version was updated
        self.meta_ads_function1.refresh_from_db()
        assert "graph.facebook.com/v21.0/" not in self.meta_ads_function1.hog
        assert "graph.facebook.com/v25.0/" in self.meta_ads_function1.hog

        # Check that the function already on the new version was left untouched
        self.meta_ads_function2.refresh_from_db()
        assert "graph.facebook.com/v25.0/" in self.meta_ads_function2.hog

        output = out.getvalue()
        assert "Found 2 destinations to process" in output
        assert "Updated: 1" in output
        assert "Update completed" in output

    @patch("posthog.management.commands.update_hog_function_code.compile_hog")
    def test_update_skips_destinations_that_fail_to_compile(self, mock_compile_hog):
        """A destination with uncompilable hog is skipped and logged, not fatal to the whole run."""
        with patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            bad_function = HogFunction.objects.create(
                team=self.team,
                name="Meta Ads Broken",
                type="destination",
                template_id="template-meta-ads",
                description="Broken hog",
                hog="let res := fetch(f'https://graph.facebook.com/v21.0/{inputs.pixelId}/events BROKEN', {}); return event;",
                enabled=True,
            )

        def fake_compile(hog, hog_type):
            if "BROKEN" in hog:
                raise Exception("unexpected character '&'")
            return "compiled_bytecode"

        mock_compile_hog.side_effect = fake_compile

        out = StringIO()
        call_command("update_hog_function_code", replace_key="meta-ads-api-version-update", stdout=out)

        # The healthy function is still migrated
        self.meta_ads_function1.refresh_from_db()
        assert "graph.facebook.com/v25.0/" in self.meta_ads_function1.hog

        # The uncompilable one is left untouched, not partially written
        bad_function.refresh_from_db()
        assert "graph.facebook.com/v21.0/" in bad_function.hog

        output = out.getvalue()
        assert "Found 3 destinations to process" in output
        assert "Updated: 1" in output
        assert "Failed: 1" in output
        assert str(bad_function.id) in output

    @patch("posthog.cdp.validation.compile_hog")
    def test_invalid_replace_key(self, mock_compile_hog):
        """Test handling of invalid replace key."""
        out = StringIO()
        call_command("update_hog_function_code", replace_key="invalid-key", stdout=out)

        # Should not have compiled anything
        assert mock_compile_hog.call_count == 0

        output = out.getvalue()
        assert "Invalid replace key provided: invalid-key" in output

    def test_missing_replace_key(self):
        """Test handling of missing replace key."""
        out = StringIO()
        call_command("update_hog_function_code", stdout=out)

        output = out.getvalue()
        assert "Invalid replace key provided: None" in output

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
        assert "Found 0 destinations to process" in output
        assert "Updated: 0" in output
