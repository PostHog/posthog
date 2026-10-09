from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.llm.system_one import NoulAnswer, RefusalAnswer, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.unprompted_question import (
    ANSWERABLE_QUESTION_ID,
    ASKS_QUESTION_ID,
    classify_unprompted_question,
    request_unprompted_answer_confirmation_activity,
)
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs

from products.slack_app.backend.models import SlackSettings, UnpromptedAnswerMode

MODULE = "posthog.temporal.ai.slack_app.activities.unprompted_question"


def _result(asks: Any, answerable: Any) -> SystemOneResult:
    return SystemOneResult(
        model="jev", answers={ASKS_QUESTION_ID: asks, ANSWERABLE_QUESTION_ID: answerable}, input_tokens=None
    )


class TestClassifyUnpromptedQuestion(SimpleTestCase):
    @parameterized.expand(
        [
            ("both confident", NoulAnswer(probability=0.97), NoulAnswer(probability=0.91), True),
            ("a question PostHog cannot answer", NoulAnswer(probability=0.97), NoulAnswer(probability=0.6), False),
            ("answerable but not a question", NoulAnswer(probability=0.5), NoulAnswer(probability=0.95), False),
            ("a refusal", NoulAnswer(probability=0.99), RefusalAnswer(), None),
        ]
    )
    def test_both_judgments_must_clear_the_threshold(self, _name, asks, answerable, expected):
        client = MagicMock()
        client.decide.return_value = _result(asks, answerable)
        with patch(f"{MODULE}.build_system_one_client", return_value=client):
            verdict = classify_unprompted_question(
                "How many people signed up last week?", team_id=1, distinct_id="user-1"
            )

        assert (verdict.answerable if verdict else None) == expected
        # The message travels as state, never inside the instructions.
        state = client.decide.call_args.kwargs["state"]
        assert state == {"message": "How many people signed up last week?"}


class TestRequestUnpromptedAnswerConfirmation(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=organization, name="Team")
        self.user = User.objects.create(email="alice@example.com", distinct_id="user-1")
        self.integration = Integration.objects.create(
            team=team, kind="slack", integration_id="T_WS", sensitive_config={"access_token": "xoxb"}
        )
        self.inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"type": "message", "channel": "C1", "user": "U_ALICE", "ts": "1.0", "text": "how many signups?"},
            integration_id=self.integration.id,
            slack_team_id="T_WS",
            user_id=self.user.id,
            unprompted_question=True,
        )

    @parameterized.expand(
        [
            ("auto answers", UnpromptedAnswerMode.AUTO, False, False),
            ("off stays quiet", UnpromptedAnswerMode.OFF, True, False),
            ("ask offers privately", UnpromptedAnswerMode.ASK, True, True),
            ("unset offers privately", None, True, True),
        ]
    )
    def test_the_authors_mode_decides(self, _name, mode, expect_stop, expect_prompt):
        if mode is not None:
            SlackSettings.objects.create(
                slack_workspace_id="T_WS", slack_user_id="U_ALICE", unprompted_answer_mode=mode
            )
        with patch("products.slack_app.backend.api._post_unprompted_answer_prompt", return_value=True) as mock_prompt:
            stop = request_unprompted_answer_confirmation_activity(self.inputs)

        assert stop is expect_stop
        assert mock_prompt.called is expect_prompt
