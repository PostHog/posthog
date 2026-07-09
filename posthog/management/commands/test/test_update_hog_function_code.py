from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.cdp.validation import compile_hog as compile_hog_for_check

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

# The powerplatform branch the migration must splice into stale Microsoft Teams functions.
POWERPLATFORM_BRANCH = "environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows"

# The exact tail shared by the standard 4-branch stock block and the powerplatform.com:443 variant.
_FOUR_BRANCH_TAIL = "not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+')) {\n    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), or Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...)')"

# Stale validation blocks that exist verbatim in production, each followed by a trivial send body.
_SEND_BODY = "\n\nlet res := fetch(inputs.webhookUrl, {'method': 'POST'});\n"

FOUR_BRANCH_STALE = (
    "if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*') and\n"
    "    not match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+') and\n"
    "    not match(inputs.webhookUrl, '^https://[^/]+.powerautomate.com/[^/]+') and\n    " + _FOUR_BRANCH_TAIL + "\n}"
) + _SEND_BODY

POWERPLATFORM_COM_STALE = (
    "if (not match(inputs.webhookUrl, '^https://[^/]+.powerplatform.com:443/[^/]+/.*') and\n"
    "    not match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+') and\n"
    "    not match(inputs.webhookUrl, '^https://[^/]+.powerautomate.com/[^/]+') and\n    " + _FOUR_BRANCH_TAIL + "\n}"
) + _SEND_BODY

ONE_BRANCH_STALE = (
    "if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*')) {\n"
    "    throw Error('Invalid URL. The URL should match the format: https://<region>.logic.azure.com:443/workflows/<workflowId>/triggers/manual/paths/invoke?...')\n}"
) + _SEND_BODY

# Same block but commented out - validation is disabled, so it already accepts any URL and must be left alone.
COMMENTED_OUT_STALE = (
    "// if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*')) {\n"
    "//     throw Error('Invalid URL.')\n// }"
) + _SEND_BODY


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
        self.assertIn("Found 2 destinations to process", output)
        self.assertIn("Updated: 1", output)
        self.assertIn("Update completed", output)

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
        self.assertIn("Found 3 destinations to process", output)
        self.assertIn("Updated: 1", output)
        self.assertIn("Failed: 1", output)
        self.assertIn(str(bad_function.id), output)

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

    def _create_teams_function(self, hog: str) -> HogFunction:
        with patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            return HogFunction.objects.create(
                team=self.team,
                name="Teams Function",
                type="destination",
                template_id="template-microsoft-teams",
                description="Test Teams Function",
                hog=hog,
                enabled=True,
            )

    @parameterized.expand(
        [
            ("four_branch", FOUR_BRANCH_STALE),
            ("powerplatform_com_variant", POWERPLATFORM_COM_STALE),
            ("one_branch", ONE_BRANCH_STALE),
        ]
    )
    def test_microsoft_teams_powerplatform_migration(self, _name, stale_hog):
        function = self._create_teams_function(stale_hog)

        with patch(
            "posthog.management.commands.update_hog_function_code.compile_hog",
            return_value="compiled_bytecode",
        ):
            out = StringIO()
            call_command("update_hog_function_code", replace_key="microsoft-teams-powerplatform-url", stdout=out)

        function.refresh_from_db()
        assert POWERPLATFORM_BRANCH in function.hog
        self.assertIn("Updated: 1", out.getvalue())
        # The migrated source must be valid Hog - guards against a typo in the replacement's to_string.
        compile_hog_for_check(function.hog, "destination")

    def test_microsoft_teams_powerplatform_cu_path_migration(self):
        # A function already deployed with the stale `direct/workflows/` regex, which rejects real
        # Power Platform environment URLs that carry a cluster segment (e.g. `/cu/11`) in the path.
        buggy_hog = (
            "if (not match(inputs.webhookUrl, "
            "'^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/workflows/.*')) {\n"
            "    throw Error('Invalid URL. The URL should match ... or Power Platform environment format "
            "(https://<tenant>.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/...)')\n}"
        ) + _SEND_BODY
        function = self._create_teams_function(buggy_hog)

        with patch(
            "posthog.management.commands.update_hog_function_code.compile_hog",
            return_value="compiled_bytecode",
        ):
            out = StringIO()
            call_command("update_hog_function_code", replace_key="microsoft-teams-powerplatform-cu-path", stdout=out)

        function.refresh_from_db()
        # Both the regex and the human-readable example in the error message are widened.
        assert "automations/direct/(.*/)?workflows/.*'" in function.hog
        assert "automations/direct/[<cluster>/]workflows/...)'" in function.hog
        assert "automations/direct/workflows/.*'" not in function.hog
        assert "automations/direct/workflows/...)'" not in function.hog
        self.assertIn("Updated: 1", out.getvalue())
        compile_hog_for_check(function.hog, "destination")

    def test_microsoft_teams_migration_leaves_functions_without_the_stale_block_untouched(self):
        function = self._create_teams_function(COMMENTED_OUT_STALE)

        out = StringIO()
        call_command("update_hog_function_code", replace_key="microsoft-teams-powerplatform-url", stdout=out)

        function.refresh_from_db()
        assert POWERPLATFORM_BRANCH not in function.hog
        self.assertIn("Updated: 0", out.getvalue())
