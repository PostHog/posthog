from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    classify_message_is_agent_directed,
    classify_untagged_followup_activity,
)

from products.slack_app.backend.models import SlackThreadTaskMapping


class TestClassifyUntaggedFollowupActivity(TestCase):
    """Activity-level tests for the classifier that now lives inside the
    mention workflow. The activity owns mapping lookup, thread-history fetch,
    and the LLM call; the webhook handler is no longer involved."""

    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@example.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        self.task = self.Task.objects.create(
            team=self.team,
            title="Fix the broken dashboard export",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = self.TaskRun.objects.create(
            task=self.task, team=self.team, status=self.TaskRun.Status.IN_PROGRESS
        )
        self.mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C001",
            thread_ts="1000.0000",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        self.inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={},
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            untagged_followup=True,
        )

    def _call(self, event_text: str = "Could you also check the export filter logic, please") -> bool:
        return classify_untagged_followup_activity(self.inputs, "C001", "1000.0000", "U_BOB", event_text)

    def test_mapping_gone_returns_false(self):
        """If the mapping vanished between routing-time and the workflow body,
        drop the followup — the user never @mentioned us in this thread, so
        kicking off any further work would be wrong."""
        self.mapping.delete()
        with patch(
            "posthog.temporal.ai.slack_app.activities.classifiers.classify_message_is_agent_directed"
        ) as mock_classify:
            assert self._call() is False
        mock_classify.assert_not_called()

    def test_classifier_true_returns_true(self):
        with (
            patch("products.slack_app.backend.services.slack_messages.cached_collect_thread_messages", return_value=[]),
            patch(
                "posthog.temporal.ai.slack_app.activities.classifiers.classify_message_is_agent_directed",
                return_value=True,
            ) as mock_classify,
        ):
            assert self._call() is True
        mock_classify.assert_called_once()
        # The mapping's task title flows through to the classifier prompt.
        assert mock_classify.call_args[0][1] == "Fix the broken dashboard export"

    def test_classifier_false_returns_false(self):
        with (
            patch("products.slack_app.backend.services.slack_messages.cached_collect_thread_messages", return_value=[]),
            patch(
                "posthog.temporal.ai.slack_app.activities.classifiers.classify_message_is_agent_directed",
                return_value=False,
            ),
        ):
            assert self._call("thanks team!") is False

    def test_history_fetch_failure_classifies_on_empty_history(self):
        """A Slack hiccup on ``conversations_replies`` falls back to classifying
        on the message text alone rather than dropping silently."""
        with (
            patch(
                "products.slack_app.backend.services.slack_messages.cached_collect_thread_messages",
                side_effect=RuntimeError("slack hiccup"),
            ),
            patch(
                "posthog.temporal.ai.slack_app.activities.classifiers.classify_message_is_agent_directed",
                return_value=True,
            ) as mock_classify,
        ):
            assert self._call() is True
        mock_classify.assert_called_once()
        assert mock_classify.call_args[0][2] == []


class TestClassifyMessageIsAgentDirected(TestCase):
    """The Haiku-backed classifier with cheap pre-LLM heuristics. Moved from
    the API module to the workflow module along with the rest of the LLM
    work."""

    def test_emoji_only_dropped_without_llm(self):
        with patch("posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client") as mock_client:
            assert classify_message_is_agent_directed(":thumbsup: :tada:", "do thing", []) is False
        mock_client.assert_not_called()

    def test_haiku_directed_true(self):
        fake_response = type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": '{"agent_directed": true}'})()},
                    )()
                ]
            },
        )()
        with patch("posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client") as mock_client:
            mock_client.return_value.chat.completions.create.return_value = fake_response
            result = classify_message_is_agent_directed("Please also check the auth flow on safari", "fix the bug", [])
        assert result is True

    def test_haiku_directed_false(self):
        fake_response = type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": '{"agent_directed": false}'})()},
                    )()
                ]
            },
        )()
        with patch("posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client") as mock_client:
            mock_client.return_value.chat.completions.create.return_value = fake_response
            result = classify_message_is_agent_directed("nice work team, going to lunch now", "fix the bug", [])
        assert result is False

    def test_haiku_failure_defaults_to_drop(self):
        """Conservative default: a false positive interrupts the agent on
        every chit-chat reply; a false negative just means the user re-tags."""
        with patch("posthog.temporal.ai.slack_app.activities.classifiers.get_llm_client") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = RuntimeError("boom")
            result = classify_message_is_agent_directed("Please also check the auth flow on safari", "fix the bug", [])
        assert result is False
