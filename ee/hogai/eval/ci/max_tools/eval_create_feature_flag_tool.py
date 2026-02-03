"""Evaluations for CreateFeatureFlagTool."""

import uuid

import pytest

from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase, Score

from posthog.schema import FeatureFlagGroupType, PersonPropertyFilter, PropertyOperator

from posthog.models import FeatureFlag

from products.feature_flags.backend.max_tools import (
    CreateFeatureFlagTool,
    FeatureFlagCreationSchema,
    MultivariateVariant,
)

from ee.hogai.eval.base import MaxPublicEval
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

    async def task_create_flag(test_case: dict):
        tool = CreateFeatureFlagTool(
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

        flag_schema = FeatureFlagCreationSchema(
            key=test_case["key"],
            name=test_case["name"],
            description=test_case.get("description"),
            active=test_case.get("active", True),
            group_type=test_case.get("group_type"),
            groups=test_case.get("groups", []),
            tags=test_case.get("tags", []),
            variants=test_case.get("variants"),
        )

        result_message, artifact = await tool._arun_impl(feature_flag=flag_schema)

        # Initialize result dict
        result: dict = {
            "message": result_message,
        }

        # Verify flag creation and properties based on test case expectations
        flag_key = artifact.get("flag_key")
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

    unique_suffix = uuid.uuid4().hex[:6]

    await MaxPublicEval(
        experiment_name="create_feature_flag",
        task=task_create_flag,  # type: ignore
        scores=[FeatureFlagOutputScorer(semantic_fields={"message", "flag_key"})],
        data=[
            # Basic feature flag creation
            EvalCase(
                input={
                    "key": f"new-homepage-{unique_suffix}",
                    "name": "New Homepage",
                    "description": "Testing the new homepage design",
                },
                expected={
                    "created": True,
                },
                metadata={"test_type": "basic_flag"},
            ),
            EvalCase(
                input={
                    "key": f"dark-mode-{unique_suffix}",
                    "name": "Dark Mode",
                    "active": False,
                },
                expected={
                    "created": True,
                },
                metadata={"test_type": "inactive_flag"},
            ),
            # Feature flags with rollout percentages
            EvalCase(
                input={
                    "key": f"new-dashboard-{unique_suffix}",
                    "name": "New Dashboard",
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[],
                            rollout_percentage=10,
                        )
                    ],
                },
                expected={
                    "rollout_percentage": 10,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "rollout_10_percent"},
            ),
            EvalCase(
                input={
                    "key": f"beta-features-{unique_suffix}",
                    "name": "Beta Features",
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[],
                            rollout_percentage=50,
                        )
                    ],
                },
                expected={
                    "rollout_percentage": 50,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "rollout_50_percent"},
            ),
            EvalCase(
                input={
                    "key": f"new-api-{unique_suffix}",
                    "name": "New API",
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[],
                            rollout_percentage=100,
                        )
                    ],
                },
                expected={
                    "rollout_percentage": 100,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "rollout_100_percent"},
            ),
            # Feature flags with property filters
            EvalCase(
                input={
                    "key": f"company-email-{unique_suffix}",
                    "name": "Company Email Users",
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[
                                PersonPropertyFilter(
                                    key="email",
                                    value="@company.com",
                                    operator=PropertyOperator.ICONTAINS,
                                )
                            ],
                            rollout_percentage=None,
                        )
                    ],
                },
                expected={
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "email_property_filter"},
            ),
            EvalCase(
                input={
                    "key": f"us-users-{unique_suffix}",
                    "name": "US Users",
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[
                                PersonPropertyFilter(
                                    key="country",
                                    value="US",
                                    operator=PropertyOperator.EXACT,
                                )
                            ],
                            rollout_percentage=None,
                        )
                    ],
                },
                expected={
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "country_property_filter"},
            ),
            EvalCase(
                input={
                    "key": f"test-email-{unique_suffix}",
                    "name": "Test Email Users",
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[
                                PersonPropertyFilter(
                                    key="email",
                                    value="@test.com",
                                    operator=PropertyOperator.ICONTAINS,
                                )
                            ],
                            rollout_percentage=25,
                        )
                    ],
                },
                expected={
                    "has_properties": True,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "property_filter_with_rollout"},
            ),
            # Duplicate handling
            EvalCase(
                input={
                    "key": duplicate_key,
                    "name": "Duplicate Flag",
                    "expected": {"is_duplicate_error": True},
                },
                expected={
                    "is_duplicate_error": True,
                },
                metadata={"test_type": "duplicate_key"},
            ),
            # Multivariate feature flags (A/B tests)
            EvalCase(
                input={
                    "key": f"ab-test-{unique_suffix}",
                    "name": "A/B Test",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=50),
                        MultivariateVariant(key="test", name="Test", rollout_percentage=50),
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "ab_test"},
            ),
            EvalCase(
                input={
                    "key": f"abc-test-{unique_suffix}",
                    "name": "A/B/C Test",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=33),
                        MultivariateVariant(key="variant_a", name="Variant A", rollout_percentage=33),
                        MultivariateVariant(key="variant_b", name="Variant B", rollout_percentage=34),
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "abc_test"},
            ),
            EvalCase(
                input={
                    "key": f"pricing-test-{unique_suffix}",
                    "name": "Pricing Test",
                    "variants": [
                        MultivariateVariant(key="control", name="Current Pricing", rollout_percentage=50),
                        MultivariateVariant(key="test", name="New Pricing", rollout_percentage=50),
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "pricing_ab_test"},
            ),
            # Multivariate with rollout
            EvalCase(
                input={
                    "key": f"ab-rollout-{unique_suffix}",
                    "name": "A/B Test with Rollout",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=50),
                        MultivariateVariant(key="test", name="Test", rollout_percentage=50),
                    ],
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[],
                            rollout_percentage=50,
                        )
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "ab_test_with_rollout"},
            ),
            EvalCase(
                input={
                    "key": f"experiment-{unique_suffix}",
                    "name": "Experiment",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=33),
                        MultivariateVariant(key="variant_a", name="Variant A", rollout_percentage=33),
                        MultivariateVariant(key="variant_b", name="Variant B", rollout_percentage=34),
                    ],
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[],
                            rollout_percentage=10,
                        )
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "multivariate_with_rollout"},
            ),
            # Multivariate with property filters
            EvalCase(
                input={
                    "key": f"email-test-{unique_suffix}",
                    "name": "Email Test",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=50),
                        MultivariateVariant(key="test", name="Test", rollout_percentage=50),
                    ],
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[
                                PersonPropertyFilter(
                                    key="email",
                                    value="@company.com",
                                    operator=PropertyOperator.ICONTAINS,
                                )
                            ],
                            rollout_percentage=None,
                        )
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "has_properties": True,
                    "variant_count": 2,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "ab_test_with_property_filter"},
            ),
            EvalCase(
                input={
                    "key": f"us-experiment-{unique_suffix}",
                    "name": "US Experiment",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=33),
                        MultivariateVariant(key="variant_a", name="Variant A", rollout_percentage=33),
                        MultivariateVariant(key="variant_b", name="Variant B", rollout_percentage=34),
                    ],
                    "groups": [
                        FeatureFlagGroupType(
                            properties=[
                                PersonPropertyFilter(
                                    key="country",
                                    value="US",
                                    operator=PropertyOperator.EXACT,
                                )
                            ],
                            rollout_percentage=None,
                        )
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "has_properties": True,
                    "variant_count": 3,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "multivariate_with_property_filter"},
            ),
            # Multivariate with custom percentages
            EvalCase(
                input={
                    "key": f"uneven-test-{unique_suffix}",
                    "name": "Uneven Test",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=70),
                        MultivariateVariant(key="test", name="Test", rollout_percentage=30),
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 2,
                    "percentages_valid": True,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "uneven_ab_test"},
            ),
            EvalCase(
                input={
                    "key": f"weighted-test-{unique_suffix}",
                    "name": "Weighted Test",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=33),
                        MultivariateVariant(key="variant_a", name="Variant A", rollout_percentage=33),
                        MultivariateVariant(key="variant_b", name="Variant B", rollout_percentage=34),
                    ],
                },
                expected={
                    "has_multivariate": True,
                    "variant_count": 3,
                    "percentages_valid": True,
                    "created": True,
                    "schema_valid": True,
                },
                metadata={"test_type": "weighted_multivariate"},
            ),
            # Error handling for invalid multivariate
            EvalCase(
                input={
                    "key": f"invalid-percentage-{unique_suffix}",
                    "name": "Invalid Percentage",
                    "variants": [
                        MultivariateVariant(key="control", name="Control", rollout_percentage=60),
                        MultivariateVariant(key="test", name="Test", rollout_percentage=50),  # Sum is 110!
                    ],
                    "expected": {"has_error": True},
                },
                expected={
                    "has_error": True,
                },
                metadata={"test_type": "invalid_percentages"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
