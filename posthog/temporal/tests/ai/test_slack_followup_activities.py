from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    cancel_posthog_code_followup_loops_activity,
    classify_posthog_code_followup_request_activity,
    create_posthog_code_followup_loop_activity,
)

FOLLOWUPS_MODULE = "posthog.temporal.ai.slack_app.activities.followups"


class SlackFollowupActivityTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="cory@example.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        self.inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"text": "@PostHog check this in two weeks", "ts": "1722400000.000100"},
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
        )
        handler_patch = patch("products.slack_app.backend.slack_thread.SlackThreadHandler")
        self.mock_handler_cls = handler_patch.start()
        self.addCleanup(handler_patch.stop)

    def posted_messages(self) -> list[str]:
        return [call.args[0] for call in self.mock_handler_cls.return_value.post_thread_message.call_args_list]


class TestClassifyFollowupRequestActivity(SlackFollowupActivityTestCase):
    def test_dark_flag_skips_the_llm_and_returns_none(self):
        with (
            patch(
                "products.slack_app.backend.feature_flags.is_slack_app_followups_enabled", return_value=False
            ) as mock_flag,
            patch(f"{FOLLOWUPS_MODULE}.classify_followup_request") as mock_classify,
        ):
            result = classify_posthog_code_followup_request_activity(self.inputs, "check this in two weeks", [])

        self.assertEqual(result.intent, "none")
        mock_flag.assert_called_once()
        mock_classify.assert_not_called()


class TestCreateFollowupLoopActivity(SlackFollowupActivityTestCase):
    RUN_AT = (datetime.now(UTC) + timedelta(days=14)).isoformat()

    def create(self):
        return create_posthog_code_followup_loop_activity(
            self.inputs,
            "C0456",
            "1722400000.000100",
            "U0789",
            self.user.id,
            "@PostHog check this in two weeks",
            [{"user": "Cory", "text": "we should watch activation after launch"}],
            self.RUN_AT,
            "Check the July cohort's activation",
        )

    def test_creates_the_loop_and_confirms_in_thread(self):
        with (
            patch("products.tasks.backend.access.has_loops_access", return_value=True),
            patch("products.tasks.backend.facade.loops.create_slack_followup_loop") as mock_create,
        ):
            handled = self.create()

        self.assertTrue(handled)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(
            kwargs["slack_thread_target"],
            {
                "integration_id": self.integration.id,
                "slack_workspace_id": "T_SLACK",
                "channel": "C0456",
                "thread_ts": "1722400000.000100",
                "requested_by_slack_user_id": "U0789",
            },
        )
        self.assertEqual(kwargs["run_at"], datetime.fromisoformat(self.RUN_AT))
        self.assertIn("watch activation after launch", kwargs["instructions"])
        confirmation = self.posted_messages()[0]
        self.assertIn("report back in this thread", confirmation)
        self.assertIn("cancel the follow-up", confirmation)

    def test_no_loops_access_falls_through_to_the_run_now_path(self):
        with (
            patch("products.tasks.backend.access.has_loops_access", return_value=False),
            patch("products.tasks.backend.facade.loops.create_slack_followup_loop") as mock_create,
        ):
            handled = self.create()

        self.assertFalse(handled)
        mock_create.assert_not_called()
        self.assertEqual(self.posted_messages(), [])

    def test_creation_failure_is_reported_in_thread_instead_of_falling_through(self):
        from products.tasks.backend.facade.loops import LoopValidationError

        with (
            patch("products.tasks.backend.access.has_loops_access", return_value=True),
            patch(
                "products.tasks.backend.facade.loops.create_slack_followup_loop",
                side_effect=LoopValidationError("The follow-up time must be in the future."),
            ),
        ):
            handled = self.create()

        self.assertTrue(handled)
        self.assertIn("couldn't schedule that follow-up", self.posted_messages()[0])


class TestCancelFollowupLoopsActivity(SlackFollowupActivityTestCase):
    def cancel(self):
        return cancel_posthog_code_followup_loops_activity(self.inputs, "C0456", "1722400000.000100", self.user.id)

    def test_cancels_and_confirms(self):
        with (
            patch("products.slack_app.backend.feature_flags.is_slack_app_followups_enabled", return_value=True),
            patch(
                "products.tasks.backend.facade.loops.disable_slack_followup_loops_for_thread", return_value=1
            ) as mock_disable,
        ):
            handled = self.cancel()

        self.assertTrue(handled)
        self.assertEqual(mock_disable.call_args.kwargs["thread_ts"], "1722400000.000100")
        self.assertIn("canceled", self.posted_messages()[0])

    def test_nothing_to_cancel_still_replies_with_guidance(self):
        with (
            patch("products.slack_app.backend.feature_flags.is_slack_app_followups_enabled", return_value=True),
            patch("products.tasks.backend.facade.loops.disable_slack_followup_loops_for_thread", return_value=0),
        ):
            handled = self.cancel()

        self.assertTrue(handled)
        self.assertIn("couldn't find a scheduled follow-up", self.posted_messages()[0])

    def test_dark_flag_falls_through(self):
        with patch("products.slack_app.backend.feature_flags.is_slack_app_followups_enabled", return_value=False):
            handled = self.cancel()

        self.assertFalse(handled)
        self.assertEqual(self.posted_messages(), [])
