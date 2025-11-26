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
async def eval_create_feature_flag(pytestconfig, demo_org_team_user):
    """Test feature flag creation tool with various scenarios."""
    _, team, user = demo_org_team_user

    conversation = await Conversation.objects.acreate(team=team, user=user)

    # Pre-create an existing flag for duplicate testing
    duplicate_key = f"existing-flag-{uuid.uuid4().hex[:8]}"
    await FeatureFlag.objects.acreate(team=team, key=duplicate_key, name="Existing Flag", created_by=user)

    # Generate unique keys for test cases
    unique_suffix = uuid.uuid4().hex[:6]

    async def task_create_flag(test_case: dict):
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

        result_message, artifact = await tool._arun_impl(instructions=test_case["instructions"])

        flag_key = artifact.get("flag_key")

        # Initialize result dict
        result: dict = {
            "message": result_message,
        }

        # Verify flag creation and properties based on test case expectations
        if flag_key:
            try:
                flag = await FeatureFlag.objects.aget(team=team, key=flag_key, deleted=False)
                result["flag_key"] = flag_key
                result["created"] = True

                # Check for rollout percentage
                groups = flag.filters.get("groups", [])
                if groups and len(groups) > 0:
                    group = groups[0]
                    rollout_percentage = group.get("rollout_percentage")
                    if rollout_percentage is not None:
                        result["rollout_percentage"] = rollout_percentage
                        result["schema_valid"] = (
                            isinstance(group.get("properties"), list)
                            and isinstance(rollout_percentage, int | float)
                            and "rollout_percentage" in group
                        )

                    # Check for properties
                    properties = group.get("properties", [])
                    if properties:
                        result["has_properties"] = True
                        result["schema_valid"] = all(
                            all(key in prop for key in ["key", "type", "value", "operator"]) for prop in properties
                        )

                # Check for multivariate
                multivariate = flag.filters.get("multivariate")
                if multivariate:
                    result["has_multivariate"] = True
                    variants = multivariate.get("variants", [])
                    result["variant_count"] = len(variants)

                    # Verify variant schema
                    schema_valid = all(
                        all(key in variant for key in ["key", "rollout_percentage"])
                        and isinstance(variant["rollout_percentage"], int | float)
                        for variant in variants
                    )
                    result["schema_valid"] = schema_valid

                    # Check percentage sum
                    total_percentage = sum(v.get("rollout_percentage", 0) for v in variants)
                    result["percentages_valid"] = total_percentage == 100

                    # Update schema_valid if percentages are expected
                    if "percentages_valid" in result:
                        result["schema_valid"] = result["schema_valid"] and result["percentages_valid"]

            except FeatureFlag.DoesNotExist:
                result["created"] = False
        else:
            result["created"] = False

        # Check for duplicate error
        if "is_duplicate_error" in test_case.get("expected", {}):
            result["is_duplicate_error"] = "already exists" in result_message.lower() if result_message else False

        # Check for general errors
        if "has_error" in test_case.get("expected", {}):
            result["has_error"] = (
                "error" in artifact
                or "invalid" in result_message.lower()
                or "must sum to 100" in result_message.lower()
            )

        return result

    await MaxPublicEval(
        experiment_name="create_feature_flag",
        task=task_create_flag,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message", "flag_key"})],
        data=[
            # Basic feature flag creation
            EvalCase(
                input={
                    "instructions": f"Create a feature flag called 'new-homepage-{unique_suffix}' for testing the new homepage design"
                },
                expected={
                    "message": f"Successfully created feature flag 'new-homepage-{unique_suffix}'",
                    "flag_key": f"new-homepage-{unique_suffix}",
                    "created": True,
                },
            ),
            EvalCase(
                input={
                    "instructions": f"Create a feature flag called 'dark-mode-{unique_suffix}' that is inactive by default"
                },
                expected={
                    "message": f"Successfully created feature flag 'dark-mode-{unique_suffix}'",
                    "flag_key": f"dark-mode-{unique_suffix}",
                    "created": True,
                },
            ),
            # Feature flags with rollout percentages
            EvalCase(
                input={
                    "instructions": f"Create a feature flag called 'new-dashboard-{unique_suffix}' with 10% rollout"
                },
                expected={
                    "message": f"Successfully created feature flag 'new-dashboard-{unique_suffix}' with 10% rollout",
                    "rollout_percentage": 10,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={"instructions": f"Create a flag called 'beta-features-{unique_suffix}' at 50% rollout"},
                expected={
                    "message": f"Successfully created feature flag 'beta-features-{unique_suffix}' with 50% rollout",
                    "rollout_percentage": 50,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={"instructions": f"Create a flag called 'new-api-{unique_suffix}' with 100% rollout"},
                expected={
                    "message": f"Successfully created feature flag 'new-api-{unique_suffix}' with 100% rollout",
                    "rollout_percentage": 100,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            # Feature flags with property filters
            EvalCase(
                input={
                    "instructions": f"Create a flag called 'company-email-{unique_suffix}' for users where email contains @company.com"
                },
                expected={
                    "message": f"Successfully created feature flag 'company-email-{unique_suffix}' for users where email contains @company.com",
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={"instructions": f"Create a flag called 'us-users-{unique_suffix}' targeting users in the US"},
                expected={
                    "message": f"Successfully created feature flag 'us-users-{unique_suffix}' targeting users in the US",
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={
                    "instructions": f"Create a flag called 'test-email-{unique_suffix}' for 25% of users where email contains @test.com"
                },
                expected={
                    "message": f"Successfully created feature flag 'test-email-{unique_suffix}' for 25% of users where email contains @test.com",
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            # Duplicate handling
            EvalCase(
                input={"instructions": f"Create a flag with key {duplicate_key}"},
                expected={
                    "message": f"Failed to create feature flag: Feature flag with key '{duplicate_key}' already exists",
                    "is_duplicate_error": True,
                },
            ),
            # Multivariate feature flags (A/B tests)
            EvalCase(
                input={
                    "instructions": f"Create an A/B test flag called 'ab-test-{unique_suffix}' with control and test variants"
                },
                expected={
                    "message": f"Successfully created feature flag 'ab-test-{unique_suffix}' with A/B test",
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={
                    "instructions": f"Create a multivariate flag called 'abc-test-{unique_suffix}' with 3 variants for testing"
                },
                expected={
                    "message": f"Successfully created feature flag 'abc-test-{unique_suffix}' with multivariate",
                    "has_multivariate": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={
                    "instructions": f"Create an A/B test flag called 'pricing-test-{unique_suffix}' for testing new pricing"
                },
                expected={
                    "message": f"Successfully created feature flag 'pricing-test-{unique_suffix}' with A/B test",
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            # Multivariate with rollout
            EvalCase(
                input={
                    "instructions": f"Create an A/B test flag called 'ab-rollout-{unique_suffix}' with control and test variants at 50% rollout"
                },
                expected={
                    "message": f"Successfully created feature flag 'ab-rollout-{unique_suffix}' with A/B test and 50% rollout",
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            EvalCase(
                input={
                    "instructions": f"Create a multivariate flag called 'experiment-{unique_suffix}' with 3 variants at 10% rollout"
                },
                expected={
                    "message": f"Successfully created feature flag 'experiment-{unique_suffix}' with multivariate and 10% rollout",
                    "has_multivariate": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            # Multivariate with property filters
            EvalCase(
                input={
                    "instructions": f"Create an A/B test flag called 'email-test-{unique_suffix}' for users where email contains @company.com with control and test variants"
                },
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
                input={
                    "instructions": f"Create a multivariate flag called 'us-experiment-{unique_suffix}' with 3 variants targeting US users"
                },
                expected={
                    "message": f"Successfully created feature flag 'us-experiment-{unique_suffix}' with multivariate targeting US users",
                    "has_multivariate": True,
                    "has_properties": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            # Multivariate with custom percentages
            EvalCase(
                input={
                    "instructions": f"Create an A/B test flag called 'uneven-test-{unique_suffix}' with control at 70% and test at 30%"
                },
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
                input={
                    "instructions": f"Create a multivariate flag called 'weighted-test-{unique_suffix}' with control (33%), variant_a (33%), variant_b (34%)"
                },
                expected={
                    "message": f"Successfully created feature flag 'weighted-test-{unique_suffix}' with multivariate",
                    "has_multivariate": True,
                    "variant_count": 3,
                    "percentages_valid": True,
                    "created": True,
                    "schema_valid": True,
                },
            ),
            # Error handling for invalid multivariate
            EvalCase(
                input={
                    "instructions": f"Create an A/B test flag called 'invalid-percentage-{unique_suffix}' with control at 60% and test at 50%"
                },
                expected={
                    "message": "The variant percentages you provided (control: 60%, test: 50%) sum to 110%, but they must sum to exactly 100%. Please adjust the percentages so they add up to 100.",
                    "has_error": True,
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )
