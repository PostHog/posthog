from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError


class TestSendDigestToTeamCommand(BaseTest):
    def test_send_digest_to_existing_team(self):
        """Test that the command successfully calls send_team_hog_functions_digest for an existing team"""
        with patch("posthog.management.commands.send_digest_to_team.send_team_hog_functions_digest") as mock_send:
            call_command("send_digest_to_team", self.team.id, "--email", "test@example.com")
            mock_send.assert_called_once_with(self.team.id, "test@example.com")

    def test_send_digest_to_nonexistent_team(self):
        """Test that the command raises CommandError for non-existent team"""
        with self.assertRaises(CommandError) as cm:
            call_command("send_digest_to_team", 99999)

        self.assertIn("Team with ID 99999 does not exist", str(cm.exception))

    def test_send_digest_with_notification_settings(self):
        """Test that the command works with teams that have members with notification settings"""
        # Set specific notification settings for the user
        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()

        with patch("posthog.management.commands.send_digest_to_team.send_team_hog_functions_digest") as mock_send:
            call_command("send_digest_to_team", self.team.id, "--email", "test@example.com")
            mock_send.assert_called_once_with(self.team.id, "test@example.com")

    def test_send_digest_handles_task_failure(self):
        """Test that the command properly handles when the digest task fails"""
        with patch("posthog.management.commands.send_digest_to_team.send_team_hog_functions_digest") as mock_send:
            mock_send.side_effect = Exception("Task failed")

            with self.assertRaises(CommandError) as cm:
                call_command("send_digest_to_team", self.team.id, "--email", "test@example.com")

            self.assertIn("Failed to send digest: Task failed", str(cm.exception))
