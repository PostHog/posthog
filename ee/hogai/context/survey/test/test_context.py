import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from posthog.models import Survey

from ee.hogai.context.survey.context import SurveyContext


class TestSurveyContext(BaseTest):
    def setUp(self):
        super().setUp()
        self.survey = Survey.objects.create(
            team=self.team,
            name="Test NPS Survey",
            description="A test survey for NPS feedback",
            type="popover",
            questions=[
                {
                    "id": "q1",
                    "type": "rating",
                    "question": "How likely are you to recommend us?",
                    "scale": 10,
                    "display": "number",
                    "lowerBoundLabel": "Not likely",
                    "upperBoundLabel": "Very likely",
                    "optional": False,
                },
                {
                    "id": "q2",
                    "type": "open",
                    "question": "What could we improve?",
                    "optional": True,
                },
            ],
            conditions={"url": "/pricing", "wait_period": 30},
        )

    def test_format_questions_rating(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_questions(self.survey)

        assert "How likely are you to recommend us?" in formatted
        assert "Type: rating" in formatted
        assert "Scale: 1-10 (number)" in formatted
        assert "Labels: Not likely to Very likely" in formatted
        assert "Optional: No" in formatted

    def test_format_questions_open(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_questions(self.survey)

        assert "What could we improve?" in formatted
        assert "Type: open" in formatted
        assert "Optional: Yes" in formatted

    def test_format_questions_empty(self):
        self.survey.questions = []
        self.survey.save()

        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_questions(self.survey)

        assert formatted == "No questions defined."

    def test_format_targeting_url(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_targeting(self.survey)

        assert "URL targeting: /pricing" in formatted

    def test_format_targeting_wait_period(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_targeting(self.survey)

        assert "Wait period: 30 seconds" in formatted

    def test_format_targeting_no_conditions(self):
        self.survey.conditions = {}
        self.survey.save()

        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_targeting(self.survey)

        assert formatted == "No specific targeting configured (shows to all users)."

    def test_get_status_draft(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        status = context._get_status(self.survey)
        assert status == "draft"

    def test_get_status_active(self):
        from django.utils import timezone

        self.survey.start_date = timezone.now()
        self.survey.save()

        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        status = context._get_status(self.survey)
        assert status == "active"

    def test_get_status_completed(self):
        from django.utils import timezone

        self.survey.start_date = timezone.now()
        self.survey.end_date = timezone.now()
        self.survey.save()

        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        status = context._get_status(self.survey)
        assert status == "completed"

    def test_get_status_archived(self):
        self.survey.archived = True
        self.survey.save()

        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        status = context._get_status(self.survey)
        assert status == "archived"

    @pytest.mark.asyncio
    async def test_aget_survey(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        survey = await context.aget_survey()

        assert survey is not None
        assert survey.name == "Test NPS Survey"

    @pytest.mark.asyncio
    async def test_aget_survey_not_found(self):
        context = SurveyContext(team=self.team, survey_id="00000000-0000-0000-0000-000000000000")
        survey = await context.aget_survey()

        assert survey is None

    @pytest.mark.asyncio
    async def test_execute_and_format(self):
        with patch.object(SurveyContext, "aget_response_count", new_callable=AsyncMock) as mock_count:
            mock_count.return_value = 42

            context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
            result = await context.execute_and_format()

            assert "Test NPS Survey" in result
            assert "popover" in result
            assert "draft" in result
            assert "How likely are you to recommend us?" in result
            assert "Total responses: 42" in result

    @pytest.mark.asyncio
    async def test_execute_and_format_not_found(self):
        context = SurveyContext(team=self.team, survey_id="00000000-0000-0000-0000-000000000000")
        result = await context.execute_and_format()

        assert "not found" in result


class TestSurveyContextChoiceQuestions(BaseTest):
    def setUp(self):
        super().setUp()
        self.survey = Survey.objects.create(
            team=self.team,
            name="Choice Survey",
            type="popover",
            questions=[
                {
                    "id": "q1",
                    "type": "single_choice",
                    "question": "What feature do you use most?",
                    "choices": ["Dashboard", "Insights", "Session Replay"],
                    "optional": False,
                },
                {
                    "id": "q2",
                    "type": "multiple_choice",
                    "question": "Which products interest you?",
                    "choices": ["Analytics", "Experiments", "Surveys"],
                    "optional": True,
                },
            ],
        )

    def test_format_questions_single_choice(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_questions(self.survey)

        assert "What feature do you use most?" in formatted
        assert "Type: single_choice" in formatted
        assert "Choices: Dashboard, Insights, Session Replay" in formatted

    def test_format_questions_multiple_choice(self):
        context = SurveyContext(team=self.team, survey_id=str(self.survey.id))
        formatted = context.format_questions(self.survey)

        assert "Which products interest you?" in formatted
        assert "Type: multiple_choice" in formatted
        assert "Choices: Analytics, Experiments, Surveys" in formatted
