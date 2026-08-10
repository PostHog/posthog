from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    cascade_posthog_code_repository_activity,
)


def _make_inputs(integration_id: int, slack_team_id: str = "T_SLACK") -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> fix the thing"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
    )


class TestCascadeTeamInstall(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.slack_integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={}
        )

    @parameterized.expand(
        [
            ("with_team_install", True),
            ("without_team_install", False),
        ]
    )
    def test_a_team_install_contributes_no_repos(self, _name, has_team_install):
        # Repo resolution reads the mentioner's personal install only, so a workspace whose
        # team install covers the repo still resolves `no_repo` for a user without one.
        if has_team_install:
            Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="gh-team-1",
                config={"account": {"name": "posthog"}},
                sensitive_config={"access_token": "gh-team-token"},
            )

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id), "fix the thing", self.user.id
        )

        assert outcome.mode == "no_repo"

    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_a_personal_install_resolves_its_single_repo(self, mock_user_github_class):
        from posthog.models.user_integration import UserIntegration

        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-user-1",
            config={},
            sensitive_config={"access_token": "gh-user-token"},
        )
        mock_user_github = MagicMock()
        mock_user_github.list_all_cached_repositories.return_value = [
            {"id": 1, "name": "posthog", "full_name": "posthog/posthog"}
        ]
        mock_user_github_class.return_value = mock_user_github

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id), "fix the thing", self.user.id
        )

        assert outcome.mode == "auto"
        assert outcome.repository == "posthog/posthog"
