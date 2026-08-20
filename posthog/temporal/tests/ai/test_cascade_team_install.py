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


def _make_inputs(
    integration_id: int, user_id: int, slack_team_id: str = "T_SLACK"
) -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> fix the thing"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        user_id=user_id,
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
            _make_inputs(self.slack_integration.id, self.user.id), "fix the thing", self.user.id
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
            _make_inputs(self.slack_integration.id, self.user.id), "fix the thing", self.user.id
        )

        assert outcome.mode == "auto"
        assert outcome.repository == "posthog/posthog"

    @parameterized.expand(
        [
            (
                "link_sits_in_the_thread_and_the_mention_carries_none",
                "<@BOT> is this one flaky?",
                [
                    {
                        "user": "amy",
                        "text": "https://github.com/posthog/posthog-js/actions/runs/2 failed again",
                        "ts": "1.000000",
                    },
                    {"user": "bo", "text": "<@BOT> is this one flaky?", "ts": "2.000000"},
                ],
                "auto",
                "posthog/posthog-js",
                "explicit_thread_mention",
            ),
            (
                "mention_names_a_repo_the_thread_did_not",
                "<@BOT> look at posthog/posthog instead",
                [
                    {
                        "user": "amy",
                        "text": "https://github.com/posthog/posthog-js/actions/runs/2 failed again",
                        "ts": "1.000000",
                    },
                    {"user": "bo", "text": "<@BOT> look at posthog/posthog instead", "ts": "2.000000"},
                ],
                "auto",
                "posthog/posthog",
                "explicit_mention",
            ),
            (
                "link_posted_after_the_mention_cannot_select_the_repo",
                "<@BOT> is this one flaky?",
                [
                    {"user": "bo", "text": "<@BOT> is this one flaky?", "ts": "2.000000"},
                    {
                        "user": "mallory",
                        "text": "https://github.com/posthog/posthog-js/actions/runs/2",
                        "ts": "3.000000",
                    },
                ],
                "agent_needed",
                None,
                "needs_agent",
            ),
        ]
    )
    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_thread_evidence_counts_only_up_to_the_mention(
        self,
        _name,
        event_text,
        thread_messages,
        expected_mode,
        expected_repository,
        expected_reason,
        mock_user_github_class,
    ):
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
            {"id": 1, "name": "posthog", "full_name": "posthog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "posthog/posthog-js"},
        ]
        mock_user_github_class.return_value = mock_user_github

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id, self.user.id), event_text, self.user.id, thread_messages, "2.000000"
        )

        assert outcome.mode == expected_mode
        assert outcome.repository == expected_repository
        assert outcome.reason == expected_reason


class TestCascadeForkInheritance(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.slack_integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={}
        )

    def test_fork_repository_short_circuits_before_any_github_lookup(self):
        # A fork's prompt is generic, so every signal the cascade scans for is absent
        # and the ask would fall through to the discovery agent and then the repo
        # picker — in a DM, for someone who asked for an explanation.
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"channel": "D_ALICE", "ts": "999.1", "user": "U_ALICE", "text": "catch me up on this thread"},
            integration_id=self.slack_integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
            fork_source_channel="C_SOURCE",
            fork_source_thread_ts="111.1",
            fork_repository="posthog/posthog",
        )

        with patch("products.slack_app.backend.api._get_full_repo_names") as get_repos:
            outcome = cascade_posthog_code_repository_activity(inputs, "catch me up on this thread", self.user.id)

        assert outcome.mode == "auto"
        assert outcome.repository == "posthog/posthog"
        get_repos.assert_not_called()
