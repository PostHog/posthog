from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User


class TestBackfillVercelSecrets(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="backfill@example.com", password="test", first_name="Test")
        self.organization = Organization.objects.create(name="Backfill Test Org")
        self.user.join(organization=self.organization, level=OrganizationMembership.Level.OWNER)

        self.vercel_teams = [
            self._team_with_vercel_resource("Vercel One"),
            self._team_with_vercel_resource("Vercel Two"),
        ]
        self.team_without_vercel = Team.objects.create(organization=self.organization, name="No Vercel")
        Integration.objects.create(
            team=self.team_without_vercel,
            kind=Integration.IntegrationKind.SLACK,
            integration_id="slack_123",
            config={},
            created_by=self.user,
        )

    def _team_with_vercel_resource(self, name: str) -> Team:
        team = Team.objects.create(organization=self.organization, name=name)
        Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": name},
            created_by=self.user,
        )
        return team

    def _call(self, *args: str) -> str:
        out = StringIO()
        call_command("backfill_vercel_secrets", *args, stdout=out)
        return out.getvalue()

    @patch("ee.management.commands.backfill_vercel_secrets.push_vercel_secrets.apply_async")
    def test_dry_run_lists_vercel_teams_without_enqueueing(self, mock_apply_async):
        output = self._call("--dry-run")

        mock_apply_async.assert_not_called()
        assert "Would enqueue a Vercel secret push for 2 team(s)" in output

        listed_team_ids = sorted(int(line) for line in output.splitlines() if line.strip().isdigit())
        assert listed_team_ids == sorted(team.pk for team in self.vercel_teams)

    @patch("ee.management.commands.backfill_vercel_secrets.push_vercel_secrets.apply_async")
    def test_enqueues_the_task_once_per_vercel_team(self, mock_apply_async):
        output = self._call()

        enqueued_team_ids = sorted(call.kwargs["args"][0] for call in mock_apply_async.call_args_list)
        assert enqueued_team_ids == sorted(team.pk for team in self.vercel_teams)
        assert "Enqueued a Vercel secret push for 2 team(s), 0 failed to enqueue" in output

    @patch("ee.management.commands.backfill_vercel_secrets.push_vercel_secrets.apply_async")
    def test_enqueues_are_staggered_two_per_second(self, mock_apply_async):
        extra_teams = [self._team_with_vercel_resource(f"Vercel Extra {i}") for i in range(3)]

        self._call()

        all_team_ids = sorted(team.pk for team in self.vercel_teams + extra_teams)
        countdown_by_team_id = {
            call.kwargs["args"][0]: call.kwargs["countdown"] for call in mock_apply_async.call_args_list
        }
        countdowns_in_enqueue_order = [countdown_by_team_id[team_id] for team_id in all_team_ids]
        assert countdowns_in_enqueue_order == [0, 0, 1, 1, 2]

    @patch("ee.management.commands.backfill_vercel_secrets.capture_exception")
    @patch("ee.management.commands.backfill_vercel_secrets.push_vercel_secrets.apply_async")
    def test_a_failing_team_does_not_halt_the_sweep(self, mock_apply_async, mock_capture_exception):
        mock_apply_async.side_effect = [Exception("broker down"), None]

        output = self._call()

        assert mock_apply_async.call_count == 2
        assert "Enqueued a Vercel secret push for 1 team(s), 1 failed to enqueue" in output
        mock_capture_exception.assert_called_once()

    @patch("ee.management.commands.backfill_vercel_secrets.push_vercel_secrets.apply_async")
    def test_reports_zero_teams_when_no_vercel_resources_exist(self, mock_apply_async):
        Integration.objects.filter(kind=Integration.IntegrationKind.VERCEL).delete()

        output = self._call()

        mock_apply_async.assert_not_called()
        assert "Enqueued a Vercel secret push for 0 team(s), 0 failed to enqueue" in output
