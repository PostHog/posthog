"""Seed helpers for sandboxed survey evals."""

from __future__ import annotations

import logging
from typing import Any

from posthog.models import FeatureFlag

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

logger = logging.getLogger(__name__)

__all__ = ["seed_survey_feature_flags"]


def _serialize_flag(flag: FeatureFlag) -> dict[str, Any]:
    return {
        "id": flag.id,
        "key": flag.key,
        "name": flag.name,
        "filters": flag.filters,
    }


def seed_survey_feature_flags(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Create feature flags used by survey targeting eval cases."""
    checkout_flag, _ = FeatureFlag.objects.update_or_create(
        team_id=context.team_id,
        key="new-checkout-flow",
        defaults={
            "name": "New Checkout Flow",
            "created_by_id": context.user_id,
            "active": True,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
        },
    )
    ab_test_flag, _ = FeatureFlag.objects.update_or_create(
        team_id=context.team_id,
        key="ab-test-experiment",
        defaults={
            "name": "A/B Test Experiment",
            "created_by_id": context.user_id,
            "active": True,
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

    feature_flags = {
        checkout_flag.key: _serialize_flag(checkout_flag),
        ab_test_flag.key: _serialize_flag(ab_test_flag),
    }
    logger.info(
        "Seeded survey feature flags for team_id=%s: %s",
        context.team_id,
        ", ".join(sorted(feature_flags)),
    )
    return {"feature_flags_by_key": feature_flags}
