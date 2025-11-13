"""Evaluations for CreateFeatureFlagTool."""

import uuid

import pytest

from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase, Score

from posthog.models import FeatureFlag

from products.feature_flags.backend.max_tools import CreateFeatureFlagTool

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation


class FeatureFlagOutputScorer(ScorerWithPartial):
    """Custom scorer for feature flag tool output that combines semantic similarity for text and exact matching for numbers/booleans."""

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
async def eval_create_feature_flag_basic(pytestconfig, demo_org_team_user):
    """Test basic feature flag creation with natural language instructions."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]
    key1 = f"new-homepage-{unique_suffix}"
    key2 = f"dark-mode-{unique_suffix}"

    async def task_create_flag(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        # Extract flag key from artifact if available
        flag_key = artifact.get("flag_key")

        # Verify flag was created
        flag_exists = False
        if flag_key:
            flag_exists = await FeatureFlag.objects.filter(team=team, key=flag_key, deleted=False).aexists()

        return {
            "message": result_message,
            "flag_key": flag_key,
            "created": flag_exists,
        }

    await MaxPublicEval(
        experiment_name="create_feature_flag_basic",
        task=task_create_flag,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message", "flag_key"})],
        data=[
            EvalCase(
                input=f"Create a feature flag called '{key1}' for testing the new homepage design",
                expected={
                    "message": f"Successfully created feature flag '{key1}'",
                    "flag_key": key1,
                    "created": True,
                },
            ),
            EvalCase(
                input=f"Create a feature flag called '{key2}' that is inactive by default",
                expected={
                    "message": f"Successfully created feature flag '{key2}'",
                    "flag_key": key2,
                    "created": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_feature_flag_with_rollout(pytestconfig, demo_org_team_user):
    """Test feature flag creation with rollout percentage from natural language."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_flag_with_rollout(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        flag_key = artifact.get("flag_key")

        # Verify exact schema structure if flag was created
        rollout_percentage = None
        schema_valid = False
        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key)
                groups = flag.filters.get("groups", [])

                if groups and len(groups) > 0:
                    group = groups[0]
                    rollout_percentage = group.get("rollout_percentage")
                    # Verify schema structure: group should have properties list and rollout_percentage
                    schema_valid = (
                        isinstance(group.get("properties"), list)
                        and isinstance(rollout_percentage, int | float)
                        and "rollout_percentage" in group
                    )
            except FeatureFlag.DoesNotExist:
                pass

        return {
            "message": result_message,
            "rollout_percentage": rollout_percentage,
            "created": flag_key is not None,
            "schema_valid": schema_valid,
        }

    await MaxPublicEval(
        experiment_name="create_feature_flag_with_rollout",
        task=task_create_flag_with_rollout,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create a feature flag called 'new-dashboard-{unique_suffix}' with 10% rollout",
                expected={
                    "message": f"Successfully created feature flag 'new-dashboard-{unique_suffix}' with 10% rollout",
                    "rollout_percentage": 10,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a flag called 'beta-features-{unique_suffix}' at 50% rollout",
                expected={
                    "message": f"Successfully created feature flag 'beta-features-{unique_suffix}' with 50% rollout",
                    "rollout_percentage": 50,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a flag called 'new-api-{unique_suffix}' with 100% rollout",
                expected={
                    "message": f"Successfully created feature flag 'new-api-{unique_suffix}' with 100% rollout",
                    "rollout_percentage": 100,
                    "created": True,
                    "schema_valid": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_feature_flag_with_property_filters(pytestconfig, demo_org_team_user):
    """Test feature flag creation with property-based targeting."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_flag_with_properties(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        flag_key = artifact.get("flag_key")

        # Verify property filter schema structure if flag was created
        property_count = 0
        schema_valid = False
        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key)
                groups = flag.filters.get("groups", [])
                schema_valid = True
                for group in groups:
                    properties = group.get("properties", [])
                    property_count += len(properties)
                    # Verify each property has the required schema structure
                    for prop in properties:
                        if not all(key in prop for key in ["key", "type", "value", "operator"]):
                            schema_valid = False
                            break
                    if not schema_valid:
                        break
            except FeatureFlag.DoesNotExist:
                pass

        return {
            "message": result_message,
            "has_properties": property_count > 0,
            "created": flag_key is not None,
            "schema_valid": schema_valid and property_count > 0,
        }

    await MaxPublicEval(
        experiment_name="create_feature_flag_with_property_filters",
        task=task_create_flag_with_properties,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create a flag called 'company-email-{unique_suffix}' for users where email contains @company.com",
                expected={
                    "message": f"Successfully created feature flag 'company-email-{unique_suffix}' for users where email contains @company.com",
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a flag called 'us-users-{unique_suffix}' targeting users in the US",
                expected={
                    "message": f"Successfully created feature flag 'us-users-{unique_suffix}' targeting users in the US",
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a flag called 'test-email-{unique_suffix}' for 25% of users where email contains @test.com",
                expected={
                    "message": f"Successfully created feature flag 'test-email-{unique_suffix}' for 25% of users where email contains @test.com",
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_feature_flag_duplicate_handling(pytestconfig, demo_org_team_user):
    """Test that the tool handles duplicate flag keys appropriately."""
    _, team, user = demo_org_team_user

    # Create an existing flag with unique key
    unique_key = f"existing-flag-{uuid.uuid4().hex[:8]}"
    await FeatureFlag.objects.acreate(team=team, key=unique_key, name="Existing Flag", created_by=user)

    conversation = await Conversation.objects.acreate(team=team, user=user)

    async def task_create_duplicate_flag(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, _artifact = await tool._arun_impl(instructions=instructions)

        return {
            "message": result_message,
            "is_duplicate_error": "already exists" in result_message.lower() if result_message else False,
        }

    await MaxPublicEval(
        experiment_name="create_feature_flag_duplicate_handling",
        task=task_create_duplicate_flag,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create a flag with key {unique_key}",
                expected={
                    "message": f"Failed to create feature flag: Feature flag with key '{unique_key}' already exists",
                    "is_duplicate_error": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_multivariate_feature_flag(pytestconfig, demo_org_team_user):
    """Test multivariate feature flag creation for A/B testing."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_multivariate_flag(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        flag_key = artifact.get("flag_key")

        # Verify multivariate schema structure if flag was created
        variant_count = 0
        schema_valid = False
        has_multivariate = False
        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key)
                multivariate = flag.filters.get("multivariate")

                if multivariate:
                    has_multivariate = True
                    variants = multivariate.get("variants", [])
                    variant_count = len(variants)

                    # Verify each variant has the required schema structure
                    schema_valid = True
                    for variant in variants:
                        # Verify variant has key and rollout_percentage (name is optional)
                        if not all(key in variant for key in ["key", "rollout_percentage"]):
                            schema_valid = False
                            break
                        # Verify rollout_percentage is a number
                        if not isinstance(variant["rollout_percentage"], int | float):
                            schema_valid = False
                            break
            except FeatureFlag.DoesNotExist:
                pass

        return {
            "message": result_message,
            "has_multivariate": has_multivariate,
            "variant_count": variant_count,
            "created": flag_key is not None,
            "schema_valid": schema_valid,
        }

    await MaxPublicEval(
        experiment_name="create_multivariate_feature_flag",
        task=task_create_multivariate_flag,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create an A/B test flag called 'ab-test-{unique_suffix}' with control and test variants",
                expected={
                    "message": f"Successfully created feature flag 'ab-test-{unique_suffix}' with A/B test",
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a multivariate flag called 'abc-test-{unique_suffix}' with 3 variants for testing",
                expected={
                    "message": f"Successfully created feature flag 'abc-test-{unique_suffix}' with multivariate",
                    "has_multivariate": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create an A/B test flag called 'pricing-test-{unique_suffix}' for testing new pricing",
                expected={
                    "message": f"Successfully created feature flag 'pricing-test-{unique_suffix}' with A/B test",
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_multivariate_with_rollout(pytestconfig, demo_org_team_user):
    """Test multivariate feature flags with rollout percentages for targeted experiments."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_multivariate_with_rollout(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        flag_key = artifact.get("flag_key")

        # Verify multivariate and rollout schema structure
        has_multivariate = False
        has_rollout = False
        variant_count = 0
        rollout_percentage = None
        schema_valid = False

        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key)

                # Check multivariate config
                multivariate = flag.filters.get("multivariate")
                if multivariate:
                    has_multivariate = True
                    variants = multivariate.get("variants", [])
                    variant_count = len(variants)

                # Check rollout in groups
                groups = flag.filters.get("groups", [])
                if groups and len(groups) > 0:
                    group = groups[0]
                    rollout_percentage = group.get("rollout_percentage")
                    has_rollout = rollout_percentage is not None

                # Verify schema
                schema_valid = has_multivariate and variant_count > 0
                if has_rollout:
                    schema_valid = schema_valid and isinstance(rollout_percentage, int | float)

            except FeatureFlag.DoesNotExist:
                pass

        return {
            "message": result_message,
            "has_multivariate": has_multivariate,
            "has_rollout": has_rollout,
            "variant_count": variant_count,
            "created": flag_key is not None,
            "schema_valid": schema_valid,
        }

    await MaxPublicEval(
        experiment_name="create_multivariate_with_rollout",
        task=task_create_multivariate_with_rollout,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create an A/B test flag called 'ab-rollout-{unique_suffix}' with control and test variants at 50% rollout",
                expected={
                    "message": f"Successfully created feature flag 'ab-rollout-{unique_suffix}' with A/B test and 50% rollout",
                    "has_multivariate": True,
                    "has_rollout": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a multivariate flag called 'experiment-{unique_suffix}' with 3 variants at 10% rollout",
                expected={
                    "message": f"Successfully created feature flag 'experiment-{unique_suffix}' with multivariate and 10% rollout",
                    "has_multivariate": True,
                    "has_rollout": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_multivariate_with_property_filters(pytestconfig, demo_org_team_user):
    """Test multivariate feature flags with property-based targeting for segment-specific experiments."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_multivariate_with_properties(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        flag_key = artifact.get("flag_key")

        # Verify multivariate and property filter schema structure
        has_multivariate = False
        has_properties = False
        variant_count = 0
        property_count = 0
        schema_valid = False

        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key)

                # Check multivariate config
                multivariate = flag.filters.get("multivariate")
                if multivariate:
                    has_multivariate = True
                    variants = multivariate.get("variants", [])
                    variant_count = len(variants)

                # Check properties in groups
                groups = flag.filters.get("groups", [])
                for group in groups:
                    properties = group.get("properties", [])
                    property_count += len(properties)
                    # Verify each property has required schema structure
                    for prop in properties:
                        if all(key in prop for key in ["key", "type", "value", "operator"]):
                            has_properties = True
                        else:
                            schema_valid = False
                            break

                # Verify schema
                schema_valid = has_multivariate and variant_count > 0 and has_properties

            except FeatureFlag.DoesNotExist:
                pass

        return {
            "message": result_message,
            "has_multivariate": has_multivariate,
            "has_properties": has_properties,
            "variant_count": variant_count,
            "created": flag_key is not None,
            "schema_valid": schema_valid,
        }

    await MaxPublicEval(
        experiment_name="create_multivariate_with_property_filters",
        task=task_create_multivariate_with_properties,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create an A/B test flag called 'email-test-{unique_suffix}' for users where email contains @company.com with control and test variants",
                expected={
                    "message": f"Successfully created feature flag 'email-test-{unique_suffix}' with A/B test for users where email contains @company.com",
                    "has_multivariate": True,
                    "has_properties": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a multivariate flag called 'us-experiment-{unique_suffix}' with 3 variants targeting US users",
                expected={
                    "message": f"Successfully created feature flag 'us-experiment-{unique_suffix}' with multivariate targeting US users",
                    "has_multivariate": True,
                    "has_properties": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_multivariate_with_custom_percentages(pytestconfig, demo_org_team_user):
    """Test multivariate feature flags with custom variant percentage distributions."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_multivariate_custom_percentages(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        flag_key = artifact.get("flag_key")

        # Verify multivariate with custom percentages
        has_multivariate = False
        variant_count = 0
        percentages_sum_to_100 = False
        schema_valid = False

        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key)

                multivariate = flag.filters.get("multivariate")
                if multivariate:
                    has_multivariate = True
                    variants = multivariate.get("variants", [])
                    variant_count = len(variants)

                    # Check if percentages sum to 100
                    total_percentage = sum(v.get("rollout_percentage", 0) for v in variants)
                    percentages_sum_to_100 = total_percentage == 100

                    # Verify schema
                    schema_valid = True
                    for variant in variants:
                        if not all(key in variant for key in ["key", "rollout_percentage"]):
                            schema_valid = False
                            break

            except FeatureFlag.DoesNotExist:
                pass

        return {
            "message": result_message,
            "has_multivariate": has_multivariate,
            "variant_count": variant_count,
            "percentages_valid": percentages_sum_to_100,
            "created": flag_key is not None,
            "schema_valid": schema_valid and percentages_sum_to_100,
        }

    await MaxPublicEval(
        experiment_name="create_multivariate_with_custom_percentages",
        task=task_create_multivariate_custom_percentages,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create an A/B test flag called 'uneven-test-{unique_suffix}' with control at 70% and test at 30%",
                expected={
                    "message": f"Successfully created feature flag 'uneven-test-{unique_suffix}' with A/B test",
                    "has_multivariate": True,
                    "variant_count": 2,
                    "percentages_valid": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input=f"Create a multivariate flag called 'weighted-test-{unique_suffix}' with control (33%), variant_a (33%), variant_b (34%)",
                expected={
                    "message": f"Successfully created feature flag 'weighted-test-{unique_suffix}' with multivariate",
                    "has_multivariate": True,
                    "variant_count": 3,
                    "percentages_valid": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_create_multivariate_error_handling(pytestconfig, demo_org_team_user):
    """Test multivariate feature flag error handling for invalid configurations."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Generate unique keys for this test run
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_invalid_multivariate(instructions: str):
        tool = await CreateFeatureFlagTool.create_tool_class(
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

        result_message, artifact = await tool._arun_impl(instructions=instructions)

        # Check if error was properly reported
        has_error = (
            "error" in artifact or "invalid" in result_message.lower() or "must sum to 100" in result_message.lower()
        )

        return {
            "message": result_message,
            "has_error": has_error,
        }

    await MaxPublicEval(
        experiment_name="create_multivariate_error_handling",
        task=task_create_invalid_multivariate,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message"})],
        data=[
            EvalCase(
                input=f"Create an A/B test flag called 'invalid-percentage-{unique_suffix}' with control at 60% and test at 50%",
                expected={
                    "message": "The variant percentages you provided (control: 60%, test: 50%) sum to 110%, but they must sum to exactly 100%. Please adjust the percentages so they add up to 100.",
                    "has_error": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )
