from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    request_untagged_followup_confirmation_activity,
)

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping, UntaggedFollowupMode


class TestRequestUntaggedFollowupConfirmationActivity(TestCase):
    """The `ask` decision, made after the classifier has passed the reply.

    Returning True holds the reply back — either waiting on the author's answer
    or because the creator switched follow-ups off while the run was in flight.
    The prompt covers every author, the thread creator included.
    """

    def setUp(self):
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@example.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        task = Task.objects.create(
            team=self.team,
            title="Fix the broken dashboard export",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C001",
            thread_ts="1000.0000",
            task=task,
            task_run=task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        self.inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"channel": "C001", "user": "U_BOB", "ts": "1001.0000", "thread_ts": "1000.0000", "text": "and this"},
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
            untagged_followup=True,
        )

    def _set_creator_mode(self, mode):
        SlackSettings.objects.update_or_create(
            slack_workspace_id="T_SLACK",
            slack_user_id="U_ALICE",
            defaults={"untagged_followup_mode": mode},
        )

    def _run(self, author: str) -> tuple[bool, bool]:
        with patch("products.slack_app.backend.api._post_untagged_followup_prompt", return_value=True) as mock_prompt:
            held = request_untagged_followup_confirmation_activity(self.inputs, "C001", "1000.0000", author)
        return held, mock_prompt.called

    @parameterized.expand(
        [
            ("ask_other_person", UntaggedFollowupMode.ASK, "U_BOB", True, True),
            # Nobody tagged the app, the creator included — so they get asked too.
            ("ask_creator", UntaggedFollowupMode.ASK, "U_ALICE", True, True),
            ("auto", UntaggedFollowupMode.AUTO, "U_BOB", False, False),
            # Switched off mid-run: hold the reply back, but there is nothing to ask.
            ("never", UntaggedFollowupMode.NEVER, "U_BOB", True, False),
        ]
    )
    def test_mode_decides_whether_the_reply_waits(self, _name, mode, author, expect_held, expect_prompt):
        self._set_creator_mode(mode)
        held, prompted = self._run(author)
        assert held is expect_held
        assert prompted is expect_prompt

    def test_thread_that_lost_its_mapping_is_held_back(self):
        # Nobody left to attribute a prompt to, and the forward would drop it anyway.
        SlackThreadTaskMapping.objects.all().delete()
        held, prompted = self._run("U_BOB")
        assert held is True
        assert prompted is False
