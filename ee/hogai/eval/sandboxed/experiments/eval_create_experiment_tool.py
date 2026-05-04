"""Experiment-creation eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/max_tools/eval_create_experiment_tool.py``.
The CI version asserts on Max's internal tool trajectory; this sandboxed
version asserts on the experiment created through the ``experiment-create``
MCP tool and the ID returned to the user.

To run:
    pytest ee/hogai/eval/sandboxed/experiments/eval_create_experiment_tool.py
"""

from __future__ import annotations

from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import (
    EXPERIMENT_CREATE_TOOL_NAME,
    FEATURE_FLAG_CREATE_TOOL_NAME,
    ExperimentCreatedAndConfigured,
    ExperimentIdInFinalMessage,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall, RequiredToolCall


def _experiment_case(
    *,
    name: str,
    prompt: str,
    name_contains: str,
    variant_count: int | None = None,
    variant_keys: list[str] | None = None,
    variant_splits: dict[str, int] | None = None,
    overall_rollout_percentage: int | None = None,
) -> SandboxedEvalCase:
    experiment_expected: dict[str, Any] = {
        "name_contains": name_contains,
        "metrics_empty": True,
        "status": "draft",
    }
    if variant_count is not None:
        experiment_expected["variant_count"] = variant_count
    if variant_keys is not None:
        experiment_expected["variant_keys"] = variant_keys
    if variant_splits is not None:
        experiment_expected["variant_splits"] = variant_splits
    if overall_rollout_percentage is not None:
        experiment_expected["overall_rollout_percentage"] = overall_rollout_percentage
    expected: dict[str, Any] = {
        "experiment_created_and_configured": experiment_expected,
    }
    return SandboxedEvalCase(name=name, prompt=prompt, expected=expected)


@pytest.mark.django_db
async def eval_create_experiment_tool(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        _experiment_case(
            name="experiment_create_pricing_page",
            prompt=(
                "Create a draft A/B test experiment named 'Pricing Test' to test our new pricing page. "
                "Choose a sensible feature flag key, do not add metrics yet, and reply with the created experiment ID."
            ),
            name_contains="pricing",
        ),
        _experiment_case(
            name="experiment_create_checkout_flow",
            prompt=(
                "Set up a draft experiment named 'Checkout Flow' to test a new checkout experience. "
                "Choose a sensible feature flag key, do not add metrics yet, and reply with the created experiment ID."
            ),
            name_contains="checkout",
        ),
        _experiment_case(
            name="experiment_create_homepage_hero",
            prompt=(
                "Create a draft A/B test experiment named 'Hero Test' for the homepage hero section. "
                "Choose a sensible feature flag key, do not add metrics yet, and reply with the created experiment ID."
            ),
            name_contains="hero",
        ),
        _experiment_case(
            name="experiment_create_multivariant_cta",
            prompt=(
                "Create a draft experiment named 'Multi-variant CTA' with exactly three variants: "
                "control, variant_a, and variant_b, split evenly, to test different call-to-action buttons. "
                "Choose a sensible feature flag key, do not add metrics yet, and reply with the created experiment ID."
            ),
            name_contains="cta",
            variant_count=3,
            variant_keys=["control", "variant_a", "variant_b"],
        ),
        _experiment_case(
            name="experiment_create_gradual_rollout_split",
            prompt=(
                "Create a draft experiment named 'Gradual Rollout' to test a new onboarding flow. "
                "The split has already been clarified: it is a variant split, not an overall rollout. "
                "Use 80% control and 20% test, with 100% overall rollout. "
                "Choose a sensible feature flag key, do not add metrics yet, and reply with the created experiment ID."
            ),
            name_contains="rollout",
            variant_count=2,
            variant_keys=["control", "test"],
            variant_splits={"control": 80, "test": 20},
            overall_rollout_percentage=100,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-experiments-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            RequiredToolCall([EXPERIMENT_CREATE_TOOL_NAME]),
            NoToolCall(forbidden={FEATURE_FLAG_CREATE_TOOL_NAME}, name="no_separate_feature_flag_create"),
            ExperimentCreatedAndConfigured(),
            ExperimentIdInFinalMessage(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
