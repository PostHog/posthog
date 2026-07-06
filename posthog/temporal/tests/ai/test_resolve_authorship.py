from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    resolve_posthog_code_authorship_activity,
)


def _make_inputs(integration_id: int, slack_team_id: str = "T_SLACK") -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> do something"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
    )


class TestResolvePostHogCodeAuthorship(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

    def _add_team_github(self) -> None:
        Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

    def _add_personal_github(self, repos: list[str] | None = None, refresh_token_expires_at: int | None = None) -> None:
        config: dict = {}
        if refresh_token_expires_at is not None:
            config["user_refresh_token_expires_at"] = refresh_token_expires_at
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="gh-1",
            config=config,
            sensitive_config={"user_access_token": "at", "user_refresh_token": "rt"},
            repository_cache=[{"full_name": name} for name in (repos or [])],
            repository_cache_updated_at=timezone.now(),
        )

    def _call(self, repository: str = "posthog/target-repo") -> str:
        return resolve_posthog_code_authorship_activity(
            _make_inputs(self.integration.id), "C123", "1234.5678", "U_ALICE", self.user.id, "wf-123", repository
        )

    @patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_personal_github_with_repo_access_proceeds_and_posts_nothing(self, mock_slack_cls, _mock_flag):
        self._add_personal_github(repos=["posthog/target-repo"])
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        assert self._call() == "proceed"
        mock_slack.client.chat_postMessage.assert_not_called()

    @parameterized.expand(
        [
            ("no_repo_access_flag_on", ["posthog/other-repo"], None, True, "awaiting_confirmation"),
            ("no_repo_access_flag_off", ["posthog/other-repo"], None, False, "blocked"),
            ("expired_refresh_token_flag_on", ["posthog/target-repo"], 1, True, "awaiting_confirmation"),
        ]
    )
    @patch("posthog.models.integration.SlackIntegration")
    def test_unusable_personal_github_never_proceeds(
        self, _name, repos, refresh_token_expires_at, flag_on, expected_status, mock_slack_cls
    ):
        self._add_personal_github(repos=repos, refresh_token_expires_at=refresh_token_expires_at)
        self._add_team_github()
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        with patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=flag_on):
            assert self._call() == expected_status

        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert "can't author PRs in `posthog/target-repo`" in kwargs["text"]

    @patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_personal_flag_off_blocks_with_single_button(self, mock_slack_cls, _mock_flag):
        self._add_team_github()
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        assert self._call() == "blocked"
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert "haven't connected" in kwargs["text"]
        action_block = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
        elements = action_block["elements"]
        assert len(elements) == 1
        assert elements[0]["text"]["text"] == "Connect GitHub"
        assert "action_id" not in elements[0]

    @patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_personal_flag_on_with_team_install_awaits_confirmation(self, mock_slack_cls, _mock_flag):
        self._add_team_github()
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        assert self._call() == "awaiting_confirmation"
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert "no personal integration setup yet" in kwargs["text"]
        assert "authored by the PostHog bot" in kwargs["text"]
        assert "set up a personal integration" in kwargs["text"]

        action_block = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
        action_ids = [e.get("action_id") for e in action_block["elements"]]
        assert "posthog_code_continue_as_bot" in action_ids
        # URL button has no action_id, so Slack sends no interactivity request.
        connect_button = next(e for e in action_block["elements"] if e.get("url"))
        assert "action_id" not in connect_button
        assert kwargs["metadata"]["event_payload"]["workflow_id"] == "wf-123"

    @patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_personal_flag_on_without_team_install_blocks(self, mock_slack_cls, _mock_flag):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        assert self._call() == "blocked"
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert "haven't connected" in kwargs["text"]

    @parameterized.expand(
        [
            ("other_service_user_integration", "other-service"),
        ]
    )
    @patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_non_github_personal_integration_does_not_count(self, _name, kind, mock_slack_cls, _mock_flag):
        UserIntegration.objects.create(user=self.user, kind=kind, integration_id="x", config={}, sensitive_config={})
        self._add_team_github()
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        assert self._call() == "awaiting_confirmation"
