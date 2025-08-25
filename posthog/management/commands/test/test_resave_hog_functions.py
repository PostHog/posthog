from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.core.management import call_command

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.integration import Integration


class TestResaveHogFunctions(BaseTest):
    def setUp(self):
        super().setUp()
        # Create two integrations
        self.integration1 = Integration.objects.create(
            team=self.team,
            kind="slack",
            config={"refreshed_at": 1234567890},
        )

        self.integration2 = Integration.objects.create(
            team=self.team,
            kind="hubspot",
            config={"refreshed_at": 1234567890},
        )

        # Create two HogFunctions that use different integrations
        with patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            self.hog_function1 = HogFunction.objects.create(
                team=self.team,
                name="Test Function 1",
                type="transformation",
                description="Test Description 1",
                hog="return event",
                enabled=True,
                inputs_schema=[{"type": "integration", "key": "integration"}],
                inputs={"integration": {"value": str(self.integration1.id)}},
            )

            self.hog_function2 = HogFunction.objects.create(
                team=self.team,
                name="Test Function 2",
                type="transformation",
                description="Test Description 2",
                hog="return event",
                enabled=True,
                inputs_schema=[{"type": "integration", "key": "integration"}],
                inputs={"integration": {"value": str(self.integration2.id)}},
            )

    @patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_resave_hog_functions(self, mock_reload):
        """Test that the command correctly identifies and resaves HogFunctions connected to integrations."""

        call_command("resave_hog_functions")

        # Verify that reload_hog_functions_on_workers was called for each function
        mock_reload.assert_has_calls(
            [
                call(team_id=self.team.id, hog_function_ids=[str(self.hog_function1.id)]),
                call(team_id=self.team.id, hog_function_ids=[str(self.hog_function2.id)]),
            ]
        )
        assert mock_reload.call_count == 2

    @patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_only_resaves_enabled_non_deleted_functions(self, mock_reload):
        """Test that the command only resaves enabled and non-deleted functions."""

        # Create a disabled function
        with patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            HogFunction.objects.create(
                team=self.team,
                name="Disabled Function",
                type="transformation",
                enabled=False,
                inputs_schema=[{"type": "integration", "key": "integration"}],
                inputs={"integration": {"value": str(self.integration1.id)}},
            )

            # Create a deleted function
            HogFunction.objects.create(
                team=self.team,
                name="Deleted Function",
                type="transformation",
                deleted=True,
                inputs_schema=[{"type": "integration", "key": "integration"}],
                inputs={"integration": {"value": str(self.integration2.id)}},
            )

        call_command("resave_hog_functions")

        # Verify only the original enabled, non-deleted functions were reloaded
        mock_reload.assert_has_calls(
            [
                call(team_id=self.team.id, hog_function_ids=[str(self.hog_function1.id)]),
                call(team_id=self.team.id, hog_function_ids=[str(self.hog_function2.id)]),
            ]
        )
        assert mock_reload.call_count == 2
