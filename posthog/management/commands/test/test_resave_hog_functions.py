from unittest.mock import patch

from django.core.management import call_command

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.test.base import BaseTest


class TestResaveHogFunctions(BaseTest):
    def setUp(self):
        super().setUp()
        # Create initial function without triggering the reload
        with patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            self.hog_function = HogFunction.objects.create(
                team=self.team,
                name="Test Function",
                type="transformation",
                description="Test Description",
                hog="return event",
                enabled=True,
            )

    @patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_resave_hog_functions(self, mock_reload):
        """Test that the command correctly resaves HogFunctions and triggers the post_save signal."""

        # Call the management command with our hog function ID
        call_command("resave_hog_functions", "--ids", str(self.hog_function.id))

        # Verify that reload_hog_functions_on_workers was called with correct arguments
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_function_ids=[str(self.hog_function.id)])

    @patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_resave_multiple_hog_functions(self, mock_reload):
        """Test that the command can handle multiple HogFunction IDs."""

        # Create a second hog function without triggering the reload
        with patch("posthog.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            second_function = HogFunction.objects.create(
                team=self.team,
                name="Second Function",
                type="transformation",
                description="Another Test",
                hog="return event",
                enabled=True,
            )

        # Call the command with both function IDs
        call_command("resave_hog_functions", "--ids", str(self.hog_function.id), str(second_function.id))

        # Verify reload was called for each function
        mock_reload.assert_any_call(team_id=self.team.id, hog_function_ids=[str(self.hog_function.id)])
        mock_reload.assert_any_call(team_id=self.team.id, hog_function_ids=[str(second_function.id)])
        assert mock_reload.call_count == 2

    def test_resave_nonexistent_function(self):
        """Test that the command handles nonexistent HogFunction IDs gracefully."""

        nonexistent_id = "00000000-0000-0000-0000-000000000000"

        # The command should run without error, even with an invalid ID
        call_command("resave_hog_functions", "--ids", nonexistent_id)
