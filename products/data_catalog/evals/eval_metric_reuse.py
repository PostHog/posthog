"""Metric reuse evals: find a governed metric in a large catalog, adapt it, and use it in the middle of a task.

Run it once per surface:

    EVAL_SURFACE=app ./bin/hogli evals eval_metric_reuse --skill-delivery bundled --provider modal
    EVAL_SURFACE=mcp ./bin/hogli evals eval_metric_reuse --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import (
    seed_account_engagement_metric,
    seed_catalog_for_board_update,
    seed_catalog_with_account_engagement,
    seed_catalog_with_mrr,
    seed_mrr_metric,
    seed_noise_catalog,
    seed_pricing_metrics,
)
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    MRR_DISTINGUISHING_TERMS,
    MRR_METRIC,
    PAYING_CUSTOMERS_METRIC,
)
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    CatalogSearchUsed,
    MetricDescribeBeforeAdaptedSql,
    MetricFound,
    MetricsCatalogBeforeDataDiscovery,
    MetricsCatalogNotQueried,
    NoDataSqlRun,
    QueryTermsUsed,
    RunOverrideUsed,
    SemanticLayerAnswer,
    TrustBadgeShown,
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


async def eval_metric_reuse(ctx: EvalContext) -> None:
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
        SandboxedEvalCase(
            name="search_by_description_only",
            prompt="Is there a saved metric for how many accounts were active each week? Show me its latest numbers.",
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "catalog_search_used": {},
                "canonical_metric_run": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name, "outcome": "succeeded"},
            },
            setup=seed_catalog_with_account_engagement,
        ),
        SandboxedEvalCase(
            name="adjust_time_window",
            prompt="Show me weekly active accounts for the last 12 weeks instead of the usual 4.",
            expected={
                "run_override_used": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name, "overrides": {"date_from": None}},
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
                **_ADAPTED_MRR,
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "keep only business/standard and business/enterprise bills"
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
        SandboxedEvalCase(
            name="midchain_pricing_case",
            prompt="Should we raise the personal/pro price from $10 to $12 a month? Build the case with numbers.",
            expected={
                "metrics_catalog_before_data_discovery": {},
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Use the governed {MRR_METRIC.name} and {PAYING_CUSTOMERS_METRIC.name} metrics for the "
                        "current revenue and customer numbers before any ad hoc query. Derive the personal/pro "
                        "share and the price-change estimate from event data, and label those parts as estimates "
                        "that are not governed metrics."
                    )
                },
            },
            setup=seed_pricing_metrics,
        ),
        SandboxedEvalCase(
            name="midchain_board_update",
            prompt="Draft a one-paragraph growth update for the board.",
            expected={
                "canonical_metric_run": {
                    "metric_name": [MRR_METRIC.name, PAYING_CUSTOMERS_METRIC.name, ACCOUNT_ENGAGEMENT_METRIC.name],
                    "outcome": "succeeded",
                },
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Ground the update in the approved {MRR_METRIC.name}, {PAYING_CUSTOMERS_METRIC.name}, and "
                        f"{ACCOUNT_ENGAGEMENT_METRIC.name} metrics, cite them as governed numbers, and keep any "
                        "figure that does not come from them clearly marked as derived."
                    )
                },
            },
            setup=seed_catalog_for_board_update,
        ),
        SandboxedEvalCase(
            name="midchain_not_needed",
            prompt="How many uploaded_file events with file_type application/pdf did we get yesterday?",
            expected={"metrics_catalog_not_queried": {}},
            setup=seed_noise_catalog,
        ),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-metric-reuse-cli",
        cases=cases,
        scorers=[
            MetricFound(),
            MetricsCatalogBeforeDataDiscovery(),
            CanonicalMetricRun(),
            TrustBadgeShown(),
            CatalogSearchUsed(),
            RunOverrideUsed(),
            NoDataSqlRun(),
            MetricDescribeBeforeAdaptedSql(),
            QueryTermsUsed(),
            MetricsCatalogNotQueried(),
            SemanticLayerAnswer(),
        ],
        ctx=ctx,
        offline_suite=offline_suite(
            "data_catalog/eval_metric_reuse::eval_metric_reuse",
            metrics=[
                "metric_found",
                "metrics_catalog_before_data_discovery",
                "canonical_metric_run",
                "trust_badge",
                "catalog_search_used",
                "run_override_used",
                "no_data_sql_run",
                "metric_describe_before_adapted_sql",
                "query_terms_used",
                "metrics_catalog_not_queried",
                "semantic_layer_answer",
            ],
        ),
    )
