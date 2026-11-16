"""Metric discovery evals: find the governed metric a question means in a catalog full of other metrics.

Run it once per surface:

    ./bin/hogli evals eval_metric_discovery --surface app --skill-delivery bundled --provider modal
    ./bin/hogli evals eval_metric_discovery --surface mcp --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import seed_catalog_with_account_engagement, seed_catalog_with_mrr
from products.data_catalog.evals.catalog_synthesizer import ACCOUNT_ENGAGEMENT_METRIC, MRR_METRIC
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    MetricFound,
    MetricsCatalogBeforeDataDiscovery,
    SemanticLayerAnswer,
    TrustBadgeShown,
)
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext

# No prompt names the metric or asks for a saved metric, so the agent must think to look in the catalog
# and then match the request to the metric's description.
_ACCOUNT_ACTIVITY_PROMPTS = (
    ("report", "Prepare a report on account activity for the last month."),
    ("health_check", "How engaged are our customer accounts lately? I want the week-by-week picture."),
    ("cs_review", "For the customer success review, how many companies used the product each week recently?"),
)


async def eval_metric_discovery(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="search_exact_name",
            prompt="Run our monthly recurring revenue metric.",
            expected={
                "metric_found": {"metric_name": MRR_METRIC.name},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"metric_name": MRR_METRIC.name, "outcome": "succeeded"},
                "trust_badge": {"shown": True},
            },
            setup=seed_catalog_with_mrr,
        ),
        SandboxedEvalCase(
            name="search_synonym_in_noise",
            prompt="What's our ARR?",
            expected={
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find the approved {MRR_METRIC.name} metric although the user asked for ARR, run it, and "
                        "derive ARR as 12 times MRR. Say that ARR is derived from the governed MRR metric and that "
                        "no governed ARR metric exists. Do not re-derive revenue from raw events."
                    )
                },
            },
            setup=seed_catalog_with_mrr,
        ),
        *(
            SandboxedEvalCase(
                name=f"search_by_description_{variant}",
                prompt=prompt,
                expected={
                    "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                    "canonical_metric_run": {
                        "metric_name": ACCOUNT_ENGAGEMENT_METRIC.name,
                        "outcome": "succeeded",
                        "allow_other_metrics": True,
                    },
                    "semantic_layer_answer": {
                        "expected_behavior": (
                            f"Find and run the approved {ACCOUNT_ENGAGEMENT_METRIC.name} metric, and report its "
                            "weekly counts of active accounts as the governed account activity numbers. Other "
                            "catalog metrics may add context, but the answer must not replace the governed weekly "
                            "account counts with a figure derived from raw events."
                        )
                    },
                },
                setup=seed_catalog_with_account_engagement,
            )
            for variant, prompt in _ACCOUNT_ACTIVITY_PROMPTS
        ),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-metric-discovery-cli",
        cases=cases,
        scorers=[
            MetricFound(),
            MetricsCatalogBeforeDataDiscovery(),
            CanonicalMetricRun(),
            TrustBadgeShown(),
            SemanticLayerAnswer(),
        ],
        ctx=ctx,
        offline_suite=offline_suite(
            "data_catalog/eval_metric_discovery::eval_metric_discovery",
            metrics=[
                "metric_found",
                "metrics_catalog_before_data_discovery",
                "canonical_metric_run",
                "trust_badge",
                "semantic_layer_answer",
            ],
        ),
    )
