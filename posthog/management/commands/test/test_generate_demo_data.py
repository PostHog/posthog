from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models import Team, User


class TestGenerateDemoData(BaseTest):
    def test_reuse_existing_account_generates_into_current_project(self) -> None:
        self.user.email = "test@posthog.com"
        self.user.save(update_fields=["email"])
        user_count = User.objects.count()
        team_count = Team.objects.count()

        with patch("posthog.management.commands.generate_demo_data.MatrixManager.run_on_team") as run_on_team:
            call_command(
                "generate_demo_data",
                reuse_existing_account=True,
                n_clusters=0,
                days_past=1,
                days_future=0,
                skip_migration_check=True,
                skip_materialization=True,
                skip_flag_sync=True,
                say_on_complete=False,
                stdout=StringIO(),
            )

        run_on_team.assert_called_once_with(self.team, self.user)
        assert User.objects.count() == user_count
        assert Team.objects.count() == team_count
        assert not User.objects.filter(email="test+1@posthog.com").exists()
