"""Eval: agent reads a shared metric and validates it against user-stated acceptance criteria.

Two cases — one where criteria match the seeded metric, one where they
don't. Agent must (1) load the metric via the saved-metrics MCP tools
and (2) reach the correct verdict citing grounded discrepancies.
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import SharedMetricValidationVerdict
from ee.hogai.eval.sandboxed.experiments.seeders import SHARED_METRIC_NAME, seed_shared_metric_purchase_count
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, RequiredToolCall


async def eval_shared_metric_validation(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        # Case 1: criteria match the seeded metric exactly. Agent should
        # affirm the match and cite the event and math.
        SandboxedEvalCase(
            name="shared_metric_matches_criteria",
            prompt=(
                f"I just defined a shared experiment metric called '{SHARED_METRIC_NAME}'. "
                "My acceptance criteria: it must count the number of `purchase_completed` "
                "events per user (a simple total count, no revenue summing). Please load "
                "the metric and tell me whether it matches my criteria. Be specific about "
                "which dimensions match or don't."
            ),
            setup=seed_shared_metric_purchase_count,
            expected={"shared_metric_validation_verdict": "match"},
        ),
        # Case 2: criteria explicitly assert a different event AND a different
        # math/aggregation than the seeded metric. Agent should reject the
        # match and name at least one specific discrepancy.
        SandboxedEvalCase(
            name="shared_metric_mismatch_criteria",
            prompt=(
                f"I just defined a shared experiment metric called '{SHARED_METRIC_NAME}'. "
                "My acceptance criteria: it must sum the `revenue` property from `$purchase` "
                "events per user (total revenue per user, not a count). Please load the "
                "metric and tell me whether it matches my criteria. Be specific about which "
                "dimensions match or don't."
            ),
            setup=seed_shared_metric_purchase_count,
            expected={"shared_metric_validation_verdict": "mismatch"},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-shared-metric-validation-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            # Agent must actually read the seeded metric — either via list
            # (to resolve by name) or retrieve (by ID). Hallucinating a
            # verdict without reading the metric should fail this scorer.
            RequiredToolCall(
                required={"experiment-saved-metrics-list", "experiment-saved-metrics-retrieve"},
                name="loaded_shared_metric",
            ),
            SharedMetricValidationVerdict(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
