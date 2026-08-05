import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from products.surveys.backend.models import Survey

from ee.surveys.summaries.headline_summary import generate_survey_headline


class TestGenerateSurveyHeadline(ClickhouseTestMixin, APIBaseTest):
    def _run_headline(self, survey: Survey) -> tuple[dict, str]:
        # Mock the LLM boundary and return (result, the survey data formatted into the prompt).
        with patch("ee.surveys.summaries.headline_summary.MaxChatOpenAI") as mock_cls:
            mock_llm = mock_cls.return_value
            mock_llm.invoke.return_value = MagicMock(content="A headline")
            result = generate_survey_headline(survey, self.team, self.user)
        prompt_messages = mock_llm.invoke.call_args[0][0]
        return result, prompt_messages[1].content

    def test_merges_answers_split_across_submission_events(self):
        rating_qid = str(uuid.uuid4())
        text_qid = str(uuid.uuid4())
        survey = Survey.objects.create(
            team=self.team,
            name="Feedback",
            type="popover",
            questions=[
                {"id": rating_qid, "type": "rating", "question": "How was it?", "scale": 10},
                {"id": text_qid, "type": "open", "question": "Any comments?"},
            ],
            start_date=datetime(2024, 5, 1, tzinfo=UTC),
            enable_partial_responses=True,
        )
        submission_id = str(uuid.uuid4())
        # Earlier event (not completed): rating only.
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="split",
            timestamp="2024-06-10 09:00:00",
            properties={
                "$survey_id": str(survey.id),
                "$survey_submission_id": submission_id,
                f"$survey_response_{rating_qid}": "9",
                "$survey_completed": False,
            },
        )
        # Later (completed) event: free text only, rating is NOT repeated.
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="split",
            timestamp="2024-06-10 09:01:00",
            properties={
                "$survey_id": str(survey.id),
                "$survey_submission_id": submission_id,
                f"$survey_response_{text_qid}": "Loved the onboarding",
                "$survey_completed": True,
            },
        )
        flush_persons_and_events()

        result, prompt = self._run_headline(survey)

        # One merged submission carrying both answers, despite each living on a different event.
        assert result["responses_sampled"] == 1
        assert "9" in prompt
        assert "Loved the onboarding" in prompt

    def test_merges_multiple_choice_across_submission_events(self):
        choice_qid = str(uuid.uuid4())
        text_qid = str(uuid.uuid4())
        survey = Survey.objects.create(
            team=self.team,
            name="Feedback",
            type="popover",
            questions=[
                {"id": choice_qid, "type": "multiple_choice", "question": "Which?", "choices": ["Blue", "Green"]},
                {"id": text_qid, "type": "open", "question": "Why?"},
            ],
            start_date=datetime(2024, 5, 1, tzinfo=UTC),
            enable_partial_responses=True,
        )
        submission_id = str(uuid.uuid4())
        # The multi-choice answer lives on the earlier event; the later event resolves it to an
        # empty array, so the merge must keep the earlier non-empty array (length > 0), not clobber it.
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="split",
            timestamp="2024-06-10 09:00:00",
            properties={
                "$survey_id": str(survey.id),
                "$survey_submission_id": submission_id,
                f"$survey_response_{choice_qid}": ["Blue", "Green"],
            },
        )
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="split",
            timestamp="2024-06-10 09:01:00",
            properties={
                "$survey_id": str(survey.id),
                "$survey_submission_id": submission_id,
                f"$survey_response_{text_qid}": "Nice palette",
            },
        )
        flush_persons_and_events()

        result, prompt = self._run_headline(survey)

        assert result["responses_sampled"] == 1
        assert "Blue" in prompt
        assert "Green" in prompt
        assert "Nice palette" in prompt

    def test_partial_responses_disabled_summarizes_only_completed(self):
        text_qid = str(uuid.uuid4())
        survey = Survey.objects.create(
            team=self.team,
            name="Feedback",
            type="popover",
            questions=[{"id": text_qid, "type": "open", "question": "Any comments?"}],
            start_date=datetime(2024, 5, 1, tzinfo=UTC),
            enable_partial_responses=False,
        )
        # Completed submission.
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="done",
            timestamp="2024-06-10 09:00:00",
            properties={
                "$survey_id": str(survey.id),
                "$survey_submission_id": str(uuid.uuid4()),
                f"$survey_response_{text_qid}": "All good",
                "$survey_completed": True,
            },
        )
        # Separate still-in-progress submission (not completed) must be excluded when partial is off.
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="wip",
            timestamp="2024-06-10 09:01:00",
            properties={
                "$survey_id": str(survey.id),
                "$survey_submission_id": str(uuid.uuid4()),
                f"$survey_response_{text_qid}": "Half written",
                "$survey_completed": False,
            },
        )
        flush_persons_and_events()

        result, prompt = self._run_headline(survey)

        assert result["responses_sampled"] == 1
        assert "All good" in prompt
        assert "Half written" not in prompt
