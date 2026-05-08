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
    ExpectedSkillsLoaded,
    ExperimentCreatedAndConfigured,
    ExperimentIdInFinalMessage,
    NoSurveyIdInFinalMessage,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolAttempt, RequiredToolAttempt

CREATING_EXPERIMENTS_SKILL_NAME = "creating-experiments"
CONFIGURING_EXPERIMENT_ROLLOUT_SKILL_NAME = "configuring-experiment-rollout"

FORBIDDEN_EXPERIMENT_CREATE_ATTEMPTS = {
    FEATURE_FLAG_CREATE_TOOL_NAME,
    "experiment-archive",
    "experiment-delete",
    "experiment-duplicate",
    "experiment-end",
    "experiment-launch",
    "experiment-pause",
    "experiment-reset",
    "experiment-resume",
    "experiment-ship-variant",
    "survey-*",
    "surveys-*",
}


def _experiment_case(
    *,
    name: str,
    prompt: str,
    name_contains: str,
    variant_count: int | None = None,
    variant_keys: list[str] | None = None,
    variant_splits: dict[str, int] | None = None,
    overall_rollout_percentage: int | None = None,
    requires_rollout_skill: bool = False,
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
        "required_skills": [CREATING_EXPERIMENTS_SKILL_NAME],
    }
    if requires_rollout_skill:
        expected["required_skills"].append(CONFIGURING_EXPERIMENT_ROLLOUT_SKILL_NAME)
    return SandboxedEvalCase(name=name, prompt=prompt, expected=expected)


@pytest.mark.django_db
async def eval_create_experiment_tool(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        _experiment_case(
            name="experiment_create_pricing_page",
            prompt=(
                "Create an A/B test experiment called 'Pricing Test' to test our new pricing page. "
                "Once it's created, send me the experiment ID."
            ),
            name_contains="pricing",
        ),
        _experiment_case(
            name="experiment_create_checkout_flow",
            prompt=(
                "Set up an experiment named 'Checkout Flow' to test a new checkout experience. "
                "Once it's created, send me the experiment ID."
            ),
            name_contains="checkout",
        ),
        _experiment_case(
            name="experiment_create_homepage_hero",
            prompt=(
                "I want to run an A/B test on our homepage hero section, call it 'Hero Test'. "
                "Once it's created, send me the experiment ID."
            ),
            name_contains="hero",
        ),
        _experiment_case(
            name="experiment_create_multivariant_cta",
            prompt=(
                "Create an experiment called 'Multi-variant CTA' with three variants: "
                "control, variant_a, and variant_b to test different call-to-action buttons. "
                "Once it's created, send me the experiment ID."
            ),
            name_contains="cta",
            variant_count=3,
            variant_keys=["control", "variant_a", "variant_b"],
            requires_rollout_skill=True,
        ),
        _experiment_case(
            name="experiment_create_gradual_rollout_split",
            prompt=(
                "Set up an experiment called 'Gradual Rollout' with experiment traffic split 80/20 "
                "between control and test to cautiously test a new onboarding flow. "
                "Once it's created, send me the experiment ID."
            ),
            name_contains="rollout",
            variant_count=2,
            variant_keys=["control", "test"],
            variant_splits={"control": 80, "test": 20},
            overall_rollout_percentage=100,
            requires_rollout_skill=True,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-experiments-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolAttempt(forbidden=FORBIDDEN_EXPERIMENT_CREATE_ATTEMPTS, name="no_forbidden_tool_attempts"),
            RequiredToolAttempt(required={EXPERIMENT_CREATE_TOOL_NAME}, name="experiment_create_attempted"),
            ExpectedSkillsLoaded(),
            ExperimentCreatedAndConfigured(),
            ExperimentIdInFinalMessage(),
            NoSurveyIdInFinalMessage(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
