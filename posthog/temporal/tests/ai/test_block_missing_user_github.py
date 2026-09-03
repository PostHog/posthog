from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    block_posthog_code_task_if_no_personal_github_activity,
)


def _make_inputs(
    integration_id: int, user_id: int, slack_team_id: str = "T_SLACK"
) -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> do something"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        user_id=user_id,
    )


class TestBlockPostHogCodeTaskIfNoPersonalGitHub(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

    @patch("posthog.temporal.ai.slack_app.activities.messaging.SlackIntegration")
    def test_returns_true_and_posts_block_when_user_has_no_personal_github(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C123"
        assert kwargs["thread_ts"] == "1234.5678"
        assert "haven't connected" in kwargs["text"]

        action_block = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
        button = action_block["elements"][0]
        assert button["text"]["text"] == "Connect GitHub"
        assert button["url"].endswith(f"/project/{self.team.id}/settings/user-personal-integrations")

    def _create_personal_github(self, *, usable: bool) -> None:
        sensitive_config: dict = {"user_access_token": "at", "user_refresh_token": "rt"}
        config: dict = {}
        if not usable:
            # Refresh token expired in the past — the row exists but can't mint a token.
            config["user_refresh_token_expires_at"] = 1
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="gh-1",
            config=config,
            sensitive_config=sensitive_config,
        )

    @patch("posthog.temporal.ai.slack_app.activities.messaging.SlackIntegration")
    def test_returns_false_and_posts_nothing_when_user_has_usable_personal_github(self, mock_slack_cls):
        self._create_personal_github(usable=True)
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is False
        mock_slack.client.chat_postMessage.assert_not_called()

    @patch("posthog.temporal.ai.slack_app.activities.messaging.SlackIntegration")
    def test_stale_personal_github_blocks_with_reconnect_wording(self, mock_slack_cls):
        self._create_personal_github(usable=False)
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert "expired" in kwargs["text"]
        action_block = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
        assert action_block["elements"][0]["text"]["text"] == "Reconnect GitHub"

    @patch("posthog.temporal.ai.slack_app.activities.messaging.SlackIntegration")
    def test_only_github_kind_counts_as_personal_integration(self, mock_slack_cls):
        UserIntegration.objects.create(
            user=self.user,
            kind="other-service",
            integration_id="x",
            config={},
            sensitive_config={},
        )
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()

    @patch("posthog.temporal.ai.slack_app.activities.messaging.SlackIntegration")
    def test_another_users_github_integration_does_not_count(self, mock_slack_cls):
        other_user = User.objects.create(email="bob@test.com")
        UserIntegration.objects.create(
            user=other_user,
            kind="github",
            integration_id="gh-2",
            config={},
            sensitive_config={"access_token": "tok"},
        )
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()
