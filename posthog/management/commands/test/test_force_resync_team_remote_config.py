from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.remote_config import RemoteConfig


class TestForceResyncTeamRemoteConfig(BaseTest):
    def setUp(self):
        super().setUp()
        RemoteConfig.objects.filter(team=self.team).delete()

    def test_requires_at_least_one_selector(self):
        with self.assertRaises(CommandError):
            call_command("force_resync_team_remote_config")

    def test_errors_when_no_teams_match(self):
        with self.assertRaises(CommandError):
            call_command("force_resync_team_remote_config", team_ids=[999_999_999])

    @patch("posthog.models.remote_config.RemoteConfig.sync")
    def test_force_resyncs_by_team_id(self, mock_sync):
        out = StringIO()
        call_command("force_resync_team_remote_config", team_ids=[self.team.id], stdout=out)

        mock_sync.assert_called_once_with(force=True)
        assert "OK" in out.getvalue()
        assert f"team_id={self.team.id}" in out.getvalue()

    @patch("posthog.models.remote_config.RemoteConfig.sync")
    def test_force_resyncs_by_api_token(self, mock_sync):
        out = StringIO()
        call_command(
            "force_resync_team_remote_config",
            api_tokens=[self.team.api_token],
            stdout=out,
        )

        mock_sync.assert_called_once_with(force=True)
        assert f"token={self.team.api_token}" in out.getvalue()

    @patch("posthog.models.remote_config.RemoteConfig.sync", side_effect=RuntimeError("boom"))
    def test_propagates_failure_via_command_error(self, _mock_sync):
        with self.assertRaises(CommandError):
            call_command("force_resync_team_remote_config", team_ids=[self.team.id])
