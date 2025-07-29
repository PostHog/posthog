import pytest
from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer

from products.surveys.backend.max_tools import CreateSurveyTool

from .conftest import MaxEval


@pytest.fixture
def call_surveys_max_tool(demo_org_team_user):
    """
    This fixture creates a properly configured SurveyCreatorTool for evaluation.
    """
    # Extract team and user from the demo fixture
    _, team, user = demo_org_team_user

    max_tool = CreateSurveyTool(team=team, user=user)
    max_tool._context = {"user_id": str(user.uuid)}  # Additional context

    async def call_max_tool(instructions: str) -> dict:
        """
        Call the survey creation tool and return structured output.
        """
        try:
            # Call the tool with the instructions
            result = await max_tool._create_survey_from_instructions(instructions)

            # Return structured output that Braintrust can understand
            return {
                "success": True,
                "survey_creation_output": result if result else None,
                "message": "Survey created successfully",
            }
        except Exception as e:
            return {"success": False, "survey_creation_output": None, "message": str(e), "error": str(e)}

    return call_max_tool


class SurveyRelevanceScorer(LLMClassifier):
    """
    Evaluate if the generated survey is relevant to the given instructions using LLM as a judge.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_relevance",
            prompt_template="""
Evaluate if the generated survey is relevant and appropriate for the given user instructions.

User Instructions: {{input}}

Generated Survey:
Name: {{output.survey_creation_output.name}}
Description: {{output.survey_creation_output.description}}
Type: {{output.survey_creation_output.type}}
Questions:
{{#output.survey_creation_output.questions}}
- {{type}}: {{question}}
{{#choices}}  Choices: {{.}}{{/choices}}
{{#scale}}  Scale: {{.}}{{/scale}}
{{/output.survey_creation_output.questions}}

Evaluation Criteria:
1. Does the survey name and description match the user's intent?
2. Are the question types appropriate for the user's request? (e.g., NPS should use rating, feedback should use open text)
3. Do the questions address what the user asked for?
4. Is the survey type (popover/widget/api) appropriate for the context?
5. Are the questions logically connected to the user's goals?

How would you rate the relevance of this survey to the user's instructions? Choose one:
- perfect: The survey perfectly matches the user's intent and requirements
- good: The survey is relevant but could be slightly better aligned
- partial: The survey is somewhat relevant but misses some key aspects
- irrelevant: The survey does not address the user's request at all
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "irrelevant": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        return super()._run_eval_sync(output, expected, **kwargs)


class SurveyQuestionQualityScorer(LLMClassifier):
    """
    Evaluate the quality of survey questions using LLM as a judge.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_question_quality",
            prompt_template="""
Evaluate the quality of the survey questions based on best practices for IN-APP survey design.

IMPORTANT CONTEXT: These are in-app surveys that appear as overlays while users are actively using the product.
Users are trying to accomplish tasks, not fill out long surveys.

User Instructions: {{input}}

Generated Survey Questions:
{{#output.survey_creation_output.questions}}
{{@index}}. {{type}}: {{question}}
{{#description}}   Description: {{.}}{{/description}}
{{#choices}}   Choices: {{.}}{{/choices}}
{{#scale}}   Scale: {{.}}{{/scale}}
{{/output.survey_creation_output.questions}}

Evaluation Criteria for IN-APP Surveys:
1. **Appropriate Length**: 1-3 questions maximum. More than 3 questions is unacceptable for in-app surveys.
2. **Focused Purpose**: Does the survey focus on ONE key insight rather than trying to gather everything?
3. **User Respect**: Are the questions respectful of user time and context (they're in the middle of using the product)?
4. **No Duplicates**: Are all questions distinct and non-repetitive?
5. **Clarity**: Are the questions clear, unambiguous, and easy to understand?
6. **Logical Flow**: Do the questions follow a logical sequence?
7. **Question Types**: Are the question types (rating, open, choice) well-suited to what they're asking?
8. **Completion-Friendly**: Are the questions designed for high completion rates in an in-app context?

CRITICAL: Surveys with more than 3 questions should be rated as "unacceptable" regardless of other quality factors.

How would you rate the overall quality of these survey questions for IN-APP use? Choose one:
- perfect: 1-2 focused, clear questions that respect user time and context
- good: 1-3 good quality questions with minor issues but appropriate for in-app use
- partial: Questions are adequate but may be slightly long or unfocused for in-app context
- irrelevant: More than 3 questions, severely unfocused, or inappropriate for in-app context
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "irrelevant": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        if not survey_output.questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        if not survey_output.questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        return super()._run_eval_sync(output, expected, **kwargs)


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
        if not survey_output.questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        # Check if first question type matches expected
        first_question = survey_output.questions[0]
        actual_type = first_question.type
        expected_type = expected.get("first_question_type")

        if actual_type == expected_type:
            return Score(
                name=self._name(),
                score=1,
                metadata={
                    "reason": "First question type matches expected",
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "survey_name": survey_output.name,
                    "total_questions": len(survey_output.questions),
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
                    "survey_name": survey_output.name,
                    "total_questions": len(survey_output.questions),
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

        # Check basic requirements and track successes/failures
        checks = []
        successes = []

        # Check 1: Has name
        checks.append("name")
        if survey_output.name:
            successes.append("name")

        # Check 2: Has description
        checks.append("description")
        if survey_output.description:
            successes.append("description")

        # Check 3: Has questions
        checks.append("questions")
        if survey_output.questions:
            successes.append("questions")

        # Check 4: Meets minimum questions requirement
        min_questions = expected.get("min_questions", 1) if expected else 1
        checks.append("min_questions")
        if len(survey_output.questions) >= min_questions:
            successes.append("min_questions")

        # Calculate proportional score
        total_checks = len(checks)
        successful_checks = len(successes)
        score = successful_checks / total_checks if total_checks > 0 else 0

        # Create list of failed checks for metadata
        failed_checks = [check for check in checks if check not in successes]

        return Score(
            name=self._name(),
            score=score,
            metadata={
                "reason": f"Survey passed {successful_checks}/{total_checks} basic requirements",
                "successful_checks": successes,
                "failed_checks": failed_checks,
                "survey_name": survey_output.name,
                "total_questions": len(survey_output.questions),
                "min_questions_required": min_questions,
            },
        )


@pytest.mark.django_db
async def eval_surveys(call_surveys_max_tool, pytestconfig):
    """
    Evaluation for survey creation functionality.
    """
    await MaxEval(
        experiment_name="surveys",
        task=call_surveys_max_tool,
        scores=[
            SurveyFirstQuestionTypeScorer(),
            SurveyCreationBasicsScorer(),
            SurveyRelevanceScorer(),
            SurveyQuestionQualityScorer(),
        ],
        data=[
            # Test case 1: NPS survey should have rating question first
            EvalCase(
                input="Create an NPS survey to measure customer loyalty",
                expected={"first_question_type": "rating", "min_questions": 1},
                metadata={"test_type": "nps_survey"},
            ),
            # Test case 2: PMF survey should have single choice question first
            EvalCase(
                input="Create a PMF survey to measure product-market fit",
                expected={"first_question_type": "single_choice", "min_questions": 1},
                metadata={"test_type": "pmf_survey"},
            ),
            # Test case 3: Open feedback survey should have open text question first
            EvalCase(
                input="Create an open feedback survey for general customer insights",
                expected={"first_question_type": "open", "min_questions": 1},
                metadata={"test_type": "open_feedback_survey"},
            ),
            # Test case 4: Comprehensive survey should still be kept short for in-app use
            EvalCase(
                input="Create a comprehensive survey to understand user demographics, usage patterns, satisfaction levels, feature preferences, and improvement suggestions. First question should be a single choice question.",
                expected={"min_questions": 1, "first_question_type": "single_choice"},
                metadata={"test_type": "comprehensive_survey_length_constraint"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
