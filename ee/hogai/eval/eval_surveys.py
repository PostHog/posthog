import pytest
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer

from products.surveys.backend.max_tools import SurveyCreatorTool

from .conftest import MaxEval


@pytest.fixture
def call_surveys_max_tool(demo_org_team_user):
    """
    This fixture creates a properly configured SurveyCreatorTool for evaluation.
    """
    # Extract team and user from the demo fixture
    _, team, user = demo_org_team_user

    max_tool = SurveyCreatorTool()

    # Set up the required attributes that the tool expects
    max_tool._team = team  # Team context for survey creation
    max_tool._user = user  # User who is creating the survey
    max_tool._context = {"user_id": str(user.uuid)}  # Additional context

    async def call_max_tool(instructions: str) -> dict:
        """
        Call the survey creation tool and return structured output.
        """
        try:
            # Call the tool with the instructions
            result = max_tool._create_survey_from_instructions(instructions)

            # Return structured output that Braintrust can understand
            return {
                "success": True,
                "survey_creation_output": result.model_dump() if result else None,
                "message": "Survey created successfully",
            }
        except Exception as e:
            return {"success": False, "survey_creation_output": None, "message": str(e), "error": str(e)}

    return call_max_tool


class SurveyFirstQuestionTypeScorer(Scorer):
    """
    Evaluate if the first question type matches what we expect for the given instructions.
    """

    def _name(self):
        return "first_question_type_correct"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Skip if no expected criteria provided
        if not expected:
            return None

        # Check if the survey was created successfully
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        # Check if survey has questions
        questions = survey_output.get("questions", [])
        if not questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        # Check if first question type matches expected
        first_question = questions[0]
        actual_type = first_question.get("type")
        expected_type = expected.get("first_question_type")

        if actual_type == expected_type:
            return Score(
                name=self._name(),
                score=1,
                metadata={
                    "reason": "First question type matches expected",
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "survey_name": survey_output.get("name"),
                    "total_questions": len(questions),
                },
            )
        else:
            return Score(
                name=self._name(),
                score=0,
                metadata={
                    "reason": f"First question type mismatch",
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "survey_name": survey_output.get("name"),
                    "total_questions": len(questions),
                },
            )


class SurveyCreationBasicsScorer(Scorer):
    """
    Evaluate basic survey creation requirements (has name, description, questions).
    """

    def _name(self):
        return "survey_creation_basics"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Check if the survey was created successfully
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        # Check basic requirements
        issues = []

        if not survey_output.get("name"):
            issues.append("Missing survey name")

        if not survey_output.get("description"):
            issues.append("Missing survey description")

        questions = survey_output.get("questions", [])
        if not questions:
            issues.append("No questions created")

        # Check minimum questions if specified
        min_questions = expected.get("min_questions", 1) if expected else 1
        if len(questions) < min_questions:
            issues.append(f"Has {len(questions)} questions, expected at least {min_questions}")

        if issues:
            return Score(
                name=self._name(),
                score=0,
                metadata={
                    "reason": "Survey missing basic requirements",
                    "issues": issues,
                    "survey_name": survey_output.get("name"),
                    "total_questions": len(questions),
                },
            )
        else:
            return Score(
                name=self._name(),
                score=1,
                metadata={
                    "reason": "Survey meets all basic requirements",
                    "survey_name": survey_output.get("name"),
                    "total_questions": len(questions),
                },
            )


@pytest.mark.django_db
async def eval_surveys(call_surveys_max_tool):
    """
    Evaluation for survey creation functionality.
    """
    await MaxEval(
        experiment_name="surveys",
        task=call_surveys_max_tool,
        scores=[
            SurveyFirstQuestionTypeScorer(),
            SurveyCreationBasicsScorer(),
        ],
        data=[
            # Test case 1: NPS survey should have rating question first
            EvalCase(
                input="Create an NPS survey to measure customer loyalty",
                expected={"first_question_type": "rating", "min_questions": 1, "survey_intent": "nps"},
                metadata={"test_type": "nps_survey"},
            ),
            # Test case 2: PMF survey should have single choice question first
            EvalCase(
                input="Create a PMF survey to measure product-market fit",
                expected={"first_question_type": "single_choice", "min_questions": 1, "survey_intent": "pmf"},
                metadata={"test_type": "pmf_survey"},
            ),
            # Test case 3: Open feedback survey should have open text question first
            EvalCase(
                input="Create an open feedback survey for general customer insights",
                expected={"first_question_type": "open", "min_questions": 1, "survey_intent": "open_feedback"},
                metadata={"test_type": "open_feedback_survey"},
            ),
        ],
    )
