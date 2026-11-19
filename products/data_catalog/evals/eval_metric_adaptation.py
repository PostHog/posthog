"""Metric adaptation evals: change a governed metric to fit the question, and keep what it measures.

Run it once per surface:

    ./bin/hogli evals eval_metric_adaptation --surface app --skill-delivery bundled --provider modal
    ./bin/hogli evals eval_metric_adaptation --surface mcp --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import seed_account_engagement_metric, seed_mrr_metric
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    MRR_DISTINGUISHING_TERMS,
    MRR_METRIC,
)
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scorers import (
    MetricDescribeBeforeAdaptedSql,
    NoDataSqlRun,
    QueryTermsUsed,
    RunOverrideUsed,
    SemanticLayerAnswer,
)
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext

_ADAPTED_MRR = {
    "metric_describe_before_adapted_sql": {},
    "query_terms_used": {"terms": list(MRR_DISTINGUISHING_TERMS)},
}


def _adapted_mrr_behavior(change: str) -> str:
    return (
        f"Find {MRR_METRIC.name} in the catalog and read its definition with metric-describe. Adapt that stored "
        f"query to {change}, and keep the paid_bill event, the 30-day window, and the personal/free exclusion. "
        "Label the result as an adaptation of the governed MRR metric, not as the approved number itself."
    )


async def eval_metric_adaptation(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="adjust_time_window",
            prompt="Show me weekly active accounts for the last 12 weeks instead of the usual 4.",
            expected={
                "run_override_used": {
                    "metric_name": ACCOUNT_ENGAGEMENT_METRIC.name,
                    "overrides": {"date_from": ["-12w", "-84d", "-3m"]},
                },
                "no_data_sql_run": {},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Run {ACCOUNT_ENGAGEMENT_METRIC.name} with a date_from override that covers 12 weeks, "
                        "keep its weekly interval, and report the 12 weekly values. Do not hand-write SQL for a "
                        "metric the run tool can re-window."
                    )
                },
            },
            setup=seed_account_engagement_metric,
        ),
        SandboxedEvalCase(
            name="adjust_grouping",
            prompt="Break our MRR down by plan.",
            expected={
                **_ADAPTED_MRR,
                "semantic_layer_answer": {"expected_behavior": _adapted_mrr_behavior("group the revenue by plan")},
            },
            setup=seed_mrr_metric,
        ),
        SandboxedEvalCase(
            name="adjust_filter",
            prompt="What's our MRR from business plans only?",
            expected={
                "metric_describe_before_adapted_sql": {},
                # A business-only filter already leaves out personal/free, so the query need not name it.
                "query_terms_used": {"terms": ["paid_bill", "business/"]},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {MRR_METRIC.name} in the catalog and read its definition with metric-describe. Adapt "
                        "that stored query to keep only business/standard and business/enterprise bills, and keep "
                        "the paid_bill event and the 30-day window. Label the result as an adaptation of the "
                        "governed MRR metric, not as the approved number itself."
                    )
                },
            },
            setup=seed_mrr_metric,
        ),
        SandboxedEvalCase(
            name="adjust_extra_column",
            prompt="Show me our MRR next to the number of accounts that paid it.",
            expected={
                **_ADAPTED_MRR,
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "add a count of distinct paying accounts next to the revenue total"
                    )
                },
            },
            setup=seed_mrr_metric,
        ),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-metric-adaptation-cli",
        cases=cases,
        scorers=[
            RunOverrideUsed(),
            NoDataSqlRun(),
            MetricDescribeBeforeAdaptedSql(),
            QueryTermsUsed(),
            SemanticLayerAnswer(),
        ],
        ctx=ctx,
        offline_suite=offline_suite(
            "data_catalog/eval_metric_adaptation::eval_metric_adaptation",
            metrics=[
                "run_override_used",
                "no_data_sql_run",
                "metric_describe_before_adapted_sql",
                "query_terms_used",
                "semantic_layer_answer",
            ],
        ),
    )
