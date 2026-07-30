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


def _repo_dict(full_name: str, repo_id: int = 1) -> dict:
    org, name = full_name.split("/")
    return {"id": repo_id, "name": name, "full_name": full_name}


class TestCascadeBotPRs(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.slack_integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={}
        )

    def _create_team_github_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="gh-team-1",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "gh-team-token"},
        )

    @parameterized.expand(
        [
            ("single_repo_auto", ["posthog/posthog"], "auto"),
            ("many_repos_agent", ["posthog/a", "posthog/b"], "agent_needed"),
        ]
    )
    @patch("products.slack_app.backend.api.GitHubIntegration")
    @patch("products.slack_app.backend.api.posthoganalytics.feature_enabled", return_value=True)
    def test_flag_on_with_team_install_resolves_repos(
        self, _name, team_repos, expected_mode, _mock_feature_enabled, mock_team_github_class
    ):
        self._create_team_github_integration()
        mock_team_github = MagicMock()
        mock_team_github.list_all_cached_repositories.return_value = [
            _repo_dict(name, i) for i, name in enumerate(team_repos)
        ]
        mock_team_github_class.return_value = mock_team_github

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id), "fix the thing", self.user.id
        )

        assert outcome.mode == expected_mode
        assert outcome.mode != "needs_user_github"

    @patch("products.slack_app.backend.api.GitHubIntegration")
    @patch("products.slack_app.backend.api.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_off_with_team_install_blocks_on_user_github(self, _mock_feature_enabled, mock_team_github_class):
        self._create_team_github_integration()

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id), "fix the thing", self.user.id
        )

        assert outcome.mode == "needs_user_github"
        mock_team_github_class.assert_not_called()
