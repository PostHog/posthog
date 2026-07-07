import dataclasses
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    block_posthog_code_task_if_no_personal_github_activity,
)
from posthog.temporal.ai.slack_app.activities.messaging import coerce_mention_inputs


def _make_inputs(integration_id: int, slack_team_id: str = "T_SLACK") -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> do something"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
    )


class TestBlockPostHogCodeTaskIfNoPersonalGitHub(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

    @parameterized.expand(
        [
            ("dataclass_inputs", False),
            # Temporal skips dataclass reconstruction when the workflow invokes this activity with
            # fewer positional args than it declares (it omits the trailing ``allow_bot_prs``), so
            # ``inputs`` arrives as a raw dict. This case guards the coercion: without it the
            # activity crashes on ``inputs.integration_id`` and the mention fails with an internal
            # error instead of posting the Connect GitHub prompt.
            ("dict_inputs", True),
        ]
    )
    @patch("posthog.models.integration.SlackIntegration")
    def test_returns_true_and_posts_block_when_user_has_no_personal_github(self, _name, inputs_as_dict, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        built = _make_inputs(self.integration.id)
        inputs: Any = dataclasses.asdict(built) if inputs_as_dict else built

        blocked = block_posthog_code_task_if_no_personal_github_activity(inputs, "C123", "1234.5678", self.user.id)

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

    @patch("posthog.models.integration.SlackIntegration")
    def test_returns_false_and_posts_nothing_when_user_has_personal_github(self, mock_slack_cls):
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="gh-1",
            config={},
            sensitive_config={"access_token": "tok"},
        )
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is False
        mock_slack.client.chat_postMessage.assert_not_called()

    @patch("posthog.models.integration.SlackIntegration")
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
            _make_inputs(self.integration.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()

    @parameterized.expand(
        [
            ("flag_on_with_team_install_proceeds", True, True, False),
            ("flag_off_with_team_install_blocks", False, True, True),
            ("flag_on_without_team_install_blocks", True, False, True),
        ]
    )
    @patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled")
    @patch("posthog.models.integration.SlackIntegration")
    def test_allow_bot_prs_gates_on_flag_and_team_install(
        self, _name, flag_on, has_team_install, expect_blocked, mock_slack_cls, mock_flag
    ):
        mock_flag.return_value = flag_on
        if has_team_install:
            Integration.objects.create(
                team=self.team,
                kind="github",
                config={"account": {"name": "posthog"}},
                sensitive_config={"access_token": "ghp-test"},
            )
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id), "C123", "1234.5678", self.user.id, True
        )

        assert blocked is expect_blocked
        assert mock_slack.client.chat_postMessage.called is expect_blocked

    @patch("posthog.models.integration.SlackIntegration")
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
            _make_inputs(self.integration.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()


class TestCoerceMentionInputs(TestCase):
    @parameterized.expand(
        [
            ("known_fields_only", {}),
            # A rolling deploy that drops a field leaves older histories carrying a key the current
            # dataclass no longer declares; reconstruction must ignore it rather than raise TypeError.
            ("tolerates_unknown_field", {"stale_removed_field": "x"}),
        ]
    )
    def test_rebuilds_dataclass_from_temporal_dict_payload(self, _name, extra_keys):
        payload = {**dataclasses.asdict(_make_inputs(123, slack_team_id="T_X")), **extra_keys}

        result = coerce_mention_inputs(payload)

        assert isinstance(result, PostHogCodeSlackMentionWorkflowInputs)
        assert result.integration_id == 123
        assert result.slack_team_id == "T_X"
