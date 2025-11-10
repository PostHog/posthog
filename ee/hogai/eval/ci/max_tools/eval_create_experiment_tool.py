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
async def eval_create_experiment_basic(pytestconfig, demo_org_team_user):
    """Test basic experiment creation."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    async def task_create_experiment(args: dict):
        # Create feature flag first (required by the tool)
        await FeatureFlag.objects.acreate(
            team=team,
            created_by=user,
            key=args["feature_flag_key"],
            name=f"Flag for {args['name']}",
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
            name=args["name"],
            feature_flag_key=args["feature_flag_key"],
            description=args.get("description"),
            type=args.get("type", "product"),
        )

        exp_created = await Experiment.objects.aexists(team=team, name=args["name"], deleted=False)

        return {
            "message": result_message,
            "experiment_created": exp_created,
            "experiment_name": artifact.get("experiment_name") if artifact else None,
        }

    await MaxPublicEval(
        experiment_name="create_experiment_basic",
        task=task_create_experiment,  # type: ignore
        scores=[ExperimentOutputScorer(semantic_fields={"message", "experiment_name"})],
        data=[
            EvalCase(
                input={"name": "Pricing Test", "feature_flag_key": "pricing-test-flag"},
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
                },
                expected={
                    "message": "Successfully created experiment",
                    "experiment_created": True,
                    "experiment_name": "Homepage Redesign",
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_experiment_types(pytestconfig, demo_org_team_user):
    """Test experiment creation with different types (product vs web)."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    async def task_create_typed_experiment(args: dict):
        # Create feature flag first
        await FeatureFlag.objects.acreate(
            team=team,
            created_by=user,
            key=args["feature_flag_key"],
            name=f"Flag for {args['name']}",
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
            name=args["name"],
            feature_flag_key=args["feature_flag_key"],
            type=args["type"],
        )

        # Verify experiment type
        experiment = await Experiment.objects.aget(team=team, name=args["name"])

        return {
            "message": result_message,
            "experiment_type": experiment.type,
            "artifact_type": artifact.get("type") if artifact else None,
        }

    await MaxPublicEval(
        experiment_name="create_experiment_types",
        task=task_create_typed_experiment,  # type: ignore
        scores=[ExperimentOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input={"name": "Product Feature Test", "feature_flag_key": "product-test", "type": "product"},
                expected={
                    "message": "Successfully created experiment",
                    "experiment_type": "product",
                    "artifact_type": "product",
                },
            ),
            EvalCase(
                input={"name": "Web UI Test", "feature_flag_key": "web-test", "type": "web"},
                expected={
                    "message": "Successfully created experiment",
                    "experiment_type": "web",
                    "artifact_type": "web",
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_experiment_with_existing_flag(pytestconfig, demo_org_team_user):
    """Test experiment creation with an existing feature flag."""
    _, team, user = demo_org_team_user

    # Create an existing flag with unique key and multivariate variants
    unique_key = f"reusable-flag-{uuid.uuid4().hex[:8]}"
    await FeatureFlag.objects.acreate(
        team=team,
        key=unique_key,
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

    conversation = await Conversation.objects.acreate(team=team, user=user)

    async def task_create_experiment_reuse_flag(args: dict):
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
            name=args["name"],
            feature_flag_key=args["feature_flag_key"],
        )

        return {
            "message": result_message,
            "experiment_created": artifact is not None and "experiment_id" in artifact,
        }

    await MaxPublicEval(
        experiment_name="create_experiment_with_existing_flag",
        task=task_create_experiment_reuse_flag,  # type: ignore
        scores=[ExperimentOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input={"name": "Reuse Flag Test", "feature_flag_key": unique_key},
                expected={
                    "message": "Successfully created experiment",
                    "experiment_created": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_experiment_duplicate_name_error(pytestconfig, demo_org_team_user):
    """Test that creating a duplicate experiment returns an error."""
    _, team, user = demo_org_team_user

    # Create an existing experiment with unique flag key
    unique_flag_key = f"test-flag-{uuid.uuid4().hex[:8]}"
    flag = await FeatureFlag.objects.acreate(team=team, key=unique_flag_key, created_by=user)
    await Experiment.objects.acreate(team=team, name="Existing Experiment", feature_flag=flag, created_by=user)

    conversation = await Conversation.objects.acreate(team=team, user=user)

    async def task_create_duplicate_experiment(args: dict):
        # Create a different flag for the duplicate attempt
        await FeatureFlag.objects.acreate(
            team=team,
            created_by=user,
            key=args["feature_flag_key"],
            name=f"Flag for {args['name']}",
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
            name=args["name"],
            feature_flag_key=args["feature_flag_key"],
        )

        return {
            "message": result_message,
            "has_error": artifact.get("error") is not None if artifact else False,
        }

    await MaxPublicEval(
        experiment_name="create_experiment_duplicate_name_error",
        task=task_create_duplicate_experiment,  # type: ignore
        scores=[ExperimentOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input={"name": "Existing Experiment", "feature_flag_key": "another-flag"},
                expected={
                    "message": "Failed to create experiment: An experiment with name 'Existing Experiment' already exists",
                    "has_error": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_experiment_flag_already_used_error(pytestconfig, demo_org_team_user):
    """Test that using a flag already tied to another experiment returns an error."""
    _, team, user = demo_org_team_user

    # Create an experiment with a flag (unique key)
    unique_flag_key = f"used-flag-{uuid.uuid4().hex[:8]}"
    flag = await FeatureFlag.objects.acreate(team=team, key=unique_flag_key, created_by=user)
    await Experiment.objects.acreate(team=team, name="First Experiment", feature_flag=flag, created_by=user)

    conversation = await Conversation.objects.acreate(team=team, user=user)

    async def task_create_experiment_with_used_flag(args: dict):
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
            name=args["name"],
            feature_flag_key=args["feature_flag_key"],
        )

        return {
            "message": result_message,
            "has_error": artifact.get("error") is not None if artifact else False,
        }

    await MaxPublicEval(
        experiment_name="create_experiment_flag_already_used_error",
        task=task_create_experiment_with_used_flag,  # type: ignore
        scores=[ExperimentOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input={"name": "Second Experiment", "feature_flag_key": unique_flag_key},
                expected={
                    "message": "Failed to create experiment: Feature flag is already used by experiment",
                    "has_error": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )
