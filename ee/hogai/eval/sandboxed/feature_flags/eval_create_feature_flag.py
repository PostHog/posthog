"""Feature flag creation eval cases for the sandboxed agent.

Intent mirrors ``ee/hogai/eval/ci/max_tools/eval_create_feature_flag_tool.py``.
The CI version asserts that Max called its internal ``create_feature_flag``
tool; this port asserts that a raw sandboxed agent uses the PostHog MCP
``create-feature-flag`` tool and creates the intended feature flag.

To run:
    pytest ee/hogai/eval/sandboxed/feature_flags/eval_create_feature_flag.py
"""

from __future__ import annotations

from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.feature_flags.scorers import (
    FEATURE_FLAG_UNRELATED_WRITE_TOOLS,
    CreatedFeatureFlagIdInOutput,
    CreateFeatureFlagToolAttempted,
    FeatureFlagCreationAccuracy,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall


def _case(
    *,
    name: str,
    prompt: str,
    expected_feature_flag: dict[str, Any],
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={"feature_flag_creation_accuracy": expected_feature_flag},
    )


@pytest.mark.django_db
async def eval_create_feature_flag(
    sandboxed_demo_data: Any,
    pytestconfig: Any,
    posthog_client: Any,
    mcp_mode: str,
) -> None:
    cases: list[SandboxedEvalCase] = [
        _case(
            name="feature_flag_basic_flag",
            prompt=(
                "Create a feature flag with key 'new-homepage-sandboxed' named 'New homepage' "
                "for testing the new homepage design. After creating it, reply with the created "
                "feature flag ID and key."
            ),
            expected_feature_flag={
                "key": "new-homepage-sandboxed",
                "active": True,
            },
        ),
        _case(
            name="feature_flag_inactive_flag",
            prompt=(
                "Create a feature flag with key 'dark-mode-sandboxed' named 'Dark mode' for dark mode, "
                "but keep it inactive. After creating it, reply with the created feature flag ID and key."
            ),
            expected_feature_flag={
                "key": "dark-mode-sandboxed",
                "active": False,
            },
        ),
        _case(
            name="feature_flag_rollout_percentage",
            prompt=(
                "Create a feature flag with key 'rollout-10-sandboxed' named '10 percent rollout' "
                "that rolls out to 10% of users. After creating it, reply with the created feature "
                "flag ID and key."
            ),
            expected_feature_flag={
                "key": "rollout-10-sandboxed",
                "active": True,
                "rollout_percentage": 10,
            },
        ),
        _case(
            name="feature_flag_ab_test",
            prompt=(
                "Create an A/B test feature flag with key 'pricing-test-sandboxed' named 'Pricing test' "
                "with control and test variants, split 50/50. After creating it, reply with the created "
                "feature flag ID and key."
            ),
            expected_feature_flag={
                "key": "pricing-test-sandboxed",
                "active": True,
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
            },
        ),
        _case(
            name="feature_flag_property_filter",
            prompt=(
                "Create a feature flag with key 'company-users-sandboxed' named 'Company users' that "
                "targets users with email containing @company.com. After creating it, reply with the "
                "created feature flag ID and key."
            ),
            expected_feature_flag={
                "key": "company-users-sandboxed",
                "active": True,
                "property_filters": [
                    {
                        "key": "email",
                        "operator": "icontains",
                        "value": "@company.com",
                        "type": "person",
                    }
                ],
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-feature-flags-create-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CreateFeatureFlagToolAttempted(),
            NoToolCall(forbidden=FEATURE_FLAG_UNRELATED_WRITE_TOOLS, name="no_unrelated_persistent_writes"),
            FeatureFlagCreationAccuracy(),
            CreatedFeatureFlagIdInOutput(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
