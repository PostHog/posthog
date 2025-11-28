"""Evaluations for CreateExperimentTool."""

import uuid

import pytest

from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase, Score

from posthog.models import Experiment, FeatureFlag

from products.experiments.backend.max_tools import CreateExperimentTool

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation


class ExperimentOutputScorer(ScorerWithPartial):
    """Custom scorer for experiment tool output that combines semantic similarity for text and exact matching for numbers/booleans."""

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
async def eval_create_experiment(pytestconfig, demo_org_team_user):
    """Test experiment creation tool with various scenarios."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Pre-create flags and experiments for error testing
    duplicate_exp_flag_key = f"test-flag-{uuid.uuid4().hex[:8]}"
    duplicate_exp_flag = await FeatureFlag.objects.acreate(team=team, key=duplicate_exp_flag_key, created_by=user)
    await Experiment.objects.acreate(
        team=team, name="Existing Experiment", feature_flag=duplicate_exp_flag, created_by=user
    )

    used_flag_key = f"used-flag-{uuid.uuid4().hex[:8]}"
    used_flag = await FeatureFlag.objects.acreate(team=team, key=used_flag_key, created_by=user)
    await Experiment.objects.acreate(team=team, name="First Experiment", feature_flag=used_flag, created_by=user)

    # Pre-create a reusable flag with multivariate variants
    reusable_flag_key = f"reusable-flag-{uuid.uuid4().hex[:8]}"
    await FeatureFlag.objects.acreate(
        team=team,
        key=reusable_flag_key,
        name="Reusable Flag",
        created_by=user,
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
    )

    async def task_create_experiment(test_case: dict):
        # Create feature flag if needed (not for error cases)
        if test_case.get("create_flag"):
            await FeatureFlag.objects.acreate(
                team=team,
                created_by=user,
                key=test_case["feature_flag_key"],
                name=f"Flag for {test_case['name']}",
                filters={
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 50},
                            {"key": "test", "name": "Test", "rollout_percentage": 50},
                        ]
                    },
                },
            )

        tool = await CreateExperimentTool.create_tool_class(
            team=team,
            user=user,
            state=AssistantState(messages=[]),
            config={
                "configurable": {
                    "thread_id": conversation.id,
                    "team": team,
                    "user": user,
                }
            },
        )

        result_message, artifact = await tool._arun_impl(
            name=test_case["name"],
            feature_flag_key=test_case["feature_flag_key"],
            description=test_case.get("description"),
            type=test_case.get("type", "product"),
        )

        # Initialize result
        result: dict = {
            "message": result_message,
        }

        # Check if experiment was created
        exp_exists = await Experiment.objects.filter(team=team, name=test_case["name"], deleted=False).aexists()
        result["experiment_created"] = exp_exists

        # Get experiment name from artifact
        if artifact:
            result["experiment_name"] = artifact.get("experiment_name")
            result["experiment_id"] = artifact.get("experiment_id")

            # Check for errors
            if "error" in artifact:
                result["has_error"] = True

        # Get experiment type if it was created
        if exp_exists:
            try:
                experiment = await Experiment.objects.aget(team=team, name=test_case["name"])
                result["experiment_type"] = experiment.type
                if artifact:
                    result["artifact_type"] = artifact.get("type")
            except Experiment.DoesNotExist:
                pass

        return result

    await MaxPublicEval(
        experiment_name="create_experiment",
        task=task_create_experiment,
        scores=[ExperimentOutputScorer(semantic_fields={"message", "experiment_name"})],
        data=[
            # Basic experiment creation
            EvalCase(
                input={
                    "name": "Pricing Test",
                    "feature_flag_key": "pricing-test-flag",
                    "create_flag": True,
                },
                expected={
                    "message": "Successfully created experiment",
                    "experiment_created": True,
                    "experiment_name": "Pricing Test",
                },
            ),
            EvalCase(
                input={
                    "name": "Homepage Redesign",
                    "feature_flag_key": "homepage-redesign",
                    "description": "Testing new homepage layout for better conversion",
                    "create_flag": True,
                },
                expected={
                    "message": "Successfully created experiment",
                    "experiment_created": True,
                    "experiment_name": "Homepage Redesign",
                },
            ),
            # Experiment creation with different types
            EvalCase(
                input={
                    "name": "Product Feature Test",
                    "feature_flag_key": "product-test",
                    "type": "product",
                    "create_flag": True,
                },
                expected={
                    "message": "Successfully created experiment",
                    "experiment_type": "product",
                    "artifact_type": "product",
                },
            ),
            EvalCase(
                input={
                    "name": "Web UI Test",
                    "feature_flag_key": "web-test",
                    "type": "web",
                    "create_flag": True,
                },
                expected={
                    "message": "Successfully created experiment",
                    "experiment_type": "web",
                    "artifact_type": "web",
                },
            ),
            # Experiment with existing flag
            EvalCase(
                input={
                    "name": "Reuse Flag Test",
                    "feature_flag_key": reusable_flag_key,
                    "create_flag": False,
                },
                expected={
                    "message": "Successfully created experiment",
                    "experiment_created": True,
                },
            ),
            # Error: Duplicate experiment name
            EvalCase(
                input={
                    "name": "Existing Experiment",
                    "feature_flag_key": "another-flag",
                    "create_flag": True,
                },
                expected={
                    "message": "Failed to create experiment: An experiment with name 'Existing Experiment' already exists",
                    "has_error": True,
                },
            ),
            # Error: Flag already used by another experiment
            EvalCase(
                input={
                    "name": "Second Experiment",
                    "feature_flag_key": used_flag_key,
                    "create_flag": False,
                },
                expected={
                    "message": "Failed to create experiment: Feature flag is already used by experiment",
                    "has_error": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )
