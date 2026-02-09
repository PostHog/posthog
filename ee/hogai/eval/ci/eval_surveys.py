"""Evaluations for CreateSurveyTool."""

import uuid

import pytest

from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase, Score

from posthog.schema import (
    SurveyCreationSchema,
    SurveyDisplayConditionsSchema,
    SurveyQuestionSchema,
    SurveyQuestionType,
    SurveyType,
)

from posthog.models import FeatureFlag, Survey

from products.surveys.backend.max_tools import CreateSurveyTool

from ee.hogai.eval.base import MaxPublicEval
from ee.models.assistant import Conversation


def unique_name(base_name: str) -> str:
    """Generate a unique survey name to avoid duplicates in demo data."""
    return f"{base_name} - {uuid.uuid4().hex[:8]}"


class SurveyOutputScorer(ScorerWithPartial):
    """Custom scorer for survey tool output that combines semantic similarity for text and exact matching for other fields."""

    def __init__(self, semantic_fields: set[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.semantic_fields = semantic_fields or {"message"}

    def _run_eval_sync(self, output: dict, expected: dict, **kwargs):
        if not expected:
            return Score(name=self._name(), score=None, metadata={"reason": "No expected value provided"})
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})

        total_fields = len(expected)
        if total_fields == 0:
            return Score(name=self._name(), score=1.0)

        score_per_field = 1.0 / total_fields
        total_score = 0.0
        metadata = {}

        for field_name, expected_value in expected.items():
            actual_value = output.get(field_name)

            if field_name in self.semantic_fields:
                # Use semantic similarity for text fields
                if actual_value is not None and expected_value is not None:
                    similarity_scorer = AnswerSimilarity(model="text-embedding-3-small")
                    result = similarity_scorer.eval(output=str(actual_value), expected=str(expected_value))
                    field_score = result.score * score_per_field
                    total_score += field_score
                    metadata[f"{field_name}_score"] = result.score
                else:
                    metadata[f"{field_name}_missing"] = True
            else:
                # Use exact match for numeric/boolean fields
                if actual_value == expected_value:
                    total_score += score_per_field
                    metadata[f"{field_name}_match"] = True
                else:
                    metadata[f"{field_name}_mismatch"] = {
                        "expected": expected_value,
                        "actual": actual_value,
                    }

        return Score(name=self._name(), score=total_score, metadata=metadata)


@pytest.mark.django_db
async def eval_surveys(pytestconfig, demo_org_team_user):
    """Test survey creation tool with various scenarios."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Get or create feature flags for targeting tests
    checkout_flag, _ = await FeatureFlag.objects.aget_or_create(
        team=team,
        key="new-checkout-flow",
        defaults={
            "name": "New Checkout Flow",
            "created_by": user,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
        },
    )

    ab_test_flag, _ = await FeatureFlag.objects.aget_or_create(
        team=team,
        key="ab-test-experiment",
        defaults={
            "name": "A/B Test Experiment",
            "created_by": user,
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "treatment", "rollout_percentage": 50},
                    ]
                },
            },
        },
    )

    async def task_create_survey(test_case: dict):
        tool = CreateSurveyTool(
            team=team,
            user=user,
            config={
                "configurable": {
                    "thread_id": conversation.id,
                    "team": team,
                    "user": user,
                }
            },
        )

        # Build the survey schema from test case with unique name to avoid duplicates
        survey_schema = SurveyCreationSchema(
            name=unique_name(test_case["name"]),
            description=test_case.get("description", ""),
            type=test_case.get("type", SurveyType.POPOVER),
            questions=test_case["questions"],
            should_launch=test_case.get("should_launch", False),
            linked_flag_id=test_case.get("linked_flag_id"),
            conditions=test_case.get("conditions"),
        )

        result_message, artifact = await tool._arun_impl(survey=survey_schema)

        # Initialize result
        result: dict = {
            "message": result_message,
        }

        # Check if survey was created
        if artifact and "survey_id" in artifact:
            survey_exists = await Survey.objects.filter(id=artifact["survey_id"], archived=False).aexists()
            result["survey_created"] = survey_exists
            result["survey_id"] = artifact["survey_id"]
            result["survey_name"] = artifact.get("survey_name")

            # Fetch the created survey for detailed checks
            if survey_exists:
                survey = await Survey.objects.aget(id=artifact["survey_id"])
                result["question_count"] = len(survey.questions) if survey.questions else 0
                result["is_launched"] = survey.start_date is not None
                result["linked_flag_id"] = survey.linked_flag_id
                result["has_conditions"] = survey.conditions is not None and bool(survey.conditions)
        else:
            result["survey_created"] = False
            result["error"] = artifact.get("error") if artifact else "Unknown error"

        return result

    await MaxPublicEval(
        experiment_name="surveys",
        task=task_create_survey,
        scores=[
            SurveyOutputScorer(semantic_fields={"message"}),
        ],
        data=[
            # Test case 1: Basic NPS survey
            EvalCase(
                input={
                    "name": "NPS Survey",
                    "description": "Net Promoter Score survey",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.RATING,
                            question="How likely are you to recommend us to a friend or colleague?",
                            scale=10,
                            display="number",
                            lowerBoundLabel="Not likely at all",
                            upperBoundLabel="Extremely likely",
                        )
                    ],
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                    "is_launched": False,
                },
                metadata={"test_type": "nps_survey"},
            ),
            # Test case 2: CSAT survey with launch
            EvalCase(
                input={
                    "name": "CSAT Survey",
                    "description": "Customer satisfaction survey",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.RATING,
                            question="How satisfied are you with our product?",
                            scale=5,
                            display="number",
                        )
                    ],
                    "should_launch": True,
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                    "is_launched": True,
                },
                metadata={"test_type": "csat_survey_launched"},
            ),
            # Test case 3: Multi-question survey (NPS + follow-up)
            EvalCase(
                input={
                    "name": "NPS with Follow-up",
                    "description": "NPS survey with optional follow-up question",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.RATING,
                            question="How likely are you to recommend us?",
                            scale=10,
                            display="number",
                        ),
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.OPEN,
                            question="What could we improve?",
                            optional=True,
                        ),
                    ],
                },
                expected={
                    "survey_created": True,
                    "question_count": 2,
                    "is_launched": False,
                },
                metadata={"test_type": "nps_with_followup"},
            ),
            # Test case 4: PMF survey with single choice
            EvalCase(
                input={
                    "name": "PMF Survey",
                    "description": "Product-market fit survey",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.SINGLE_CHOICE,
                            question="How would you feel if you could no longer use our product?",
                            choices=["Very disappointed", "Somewhat disappointed", "Not disappointed"],
                        )
                    ],
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                    "is_launched": False,
                },
                metadata={"test_type": "pmf_survey"},
            ),
            # Test case 5: Survey with feature flag targeting
            EvalCase(
                input={
                    "name": "Checkout Feedback",
                    "description": "Feedback for new checkout flow users",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.OPEN,
                            question="How was your checkout experience?",
                        )
                    ],
                    "linked_flag_id": checkout_flag.id,
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                    "linked_flag_id": checkout_flag.id,
                },
                metadata={"test_type": "feature_flag_targeting"},
            ),
            # Test case 6: Survey with feature flag variant targeting
            EvalCase(
                input={
                    "name": "A/B Test Treatment Survey",
                    "description": "Survey for users in treatment variant",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.RATING,
                            question="How do you like the new design?",
                            scale=5,
                        )
                    ],
                    "linked_flag_id": ab_test_flag.id,
                    "conditions": SurveyDisplayConditionsSchema(linkedFlagVariant="treatment"),
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                    "linked_flag_id": ab_test_flag.id,
                    "has_conditions": True,
                },
                metadata={"test_type": "feature_flag_variant_targeting"},
            ),
            # Test case 7: Survey with URL conditions
            EvalCase(
                input={
                    "name": "Pricing Page Feedback",
                    "description": "Feedback from pricing page visitors",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.SINGLE_CHOICE,
                            question="Is our pricing clear?",
                            choices=["Yes, very clear", "Somewhat clear", "Not clear at all"],
                        )
                    ],
                    "conditions": SurveyDisplayConditionsSchema(
                        url="/pricing",
                        urlMatchType="icontains",
                    ),
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                    "has_conditions": True,
                },
                metadata={"test_type": "url_targeting"},
            ),
            # Test case 8: Multiple choice survey
            EvalCase(
                input={
                    "name": "Feature Usage Survey",
                    "description": "Survey about feature usage",
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.MULTIPLE_CHOICE,
                            question="Which features do you use most?",
                            choices=["Dashboard", "Insights", "Session Replay", "Feature Flags", "Experiments"],
                        )
                    ],
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                },
                metadata={"test_type": "multiple_choice"},
            ),
            # Test case 9: Widget type survey
            EvalCase(
                input={
                    "name": "Widget Feedback",
                    "description": "Widget-based feedback survey",
                    "type": SurveyType.WIDGET,
                    "questions": [
                        SurveyQuestionSchema(
                            type=SurveyQuestionType.OPEN,
                            question="What do you think of our product?",
                        )
                    ],
                },
                expected={
                    "survey_created": True,
                    "question_count": 1,
                },
                metadata={"test_type": "widget_type"},
            ),
            # Test case 10: Empty questions (should fail validation)
            EvalCase(
                input={
                    "name": "Invalid Survey",
                    "description": "Survey with no questions",
                    "questions": [],
                },
                expected={
                    "survey_created": False,
                },
                metadata={"test_type": "validation_no_questions"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
