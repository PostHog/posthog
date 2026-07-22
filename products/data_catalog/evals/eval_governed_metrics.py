"""Governed-metrics (semantic layer) evals for the sandboxed agent.

Each case seeds one arm of the catalog (approved / proposed / drifted / empty) into the
per-case team, asks a headline-business-number question, and grades the trust behavior the
``execute-sql`` metric-discovery steering asks for:

* approved & not drifted → discover before data access, run the canonical metric, and
  recheck its trust state;
* multiple materially different approved matches → clarify instead of guessing;
* proposed, drifted, empty, or failed canonical paths → disclose and label any fallback
  noncanonical;
* ordinary event/property exploration → no detour through the catalog at all.

Prompts read like real user questions and never mention ``information_schema``. Approved,
non-drifted matches run through ``data-catalog-metric-run``; deterministic scorers verify
both catalog-first ordering and the expected runner outcome.

To run a single case::

    flox activate -- bash -c "hogli evals eval_governed_metrics --eval governed_metric_approved"
"""

from __future__ import annotations

from products.data_catalog.evals.constants import (
    APPROVED_METRIC_NAME,
    CURRENT_TOP_CUSTOMERS_METRIC_NAME,
    DECOY_INSIGHT_NAMES,
    DRIFTED_METRIC_NAME,
    PROPOSED_METRIC_NAME,
    TOP_CUSTOMERS_METRIC_NAME,
)
from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    GovernedBehaviorCorrectness,
    MetricsCatalogBeforeAnswer,
    MetricsCatalogBeforeDataDiscovery,
    MetricsCatalogNotQueried,
    MetricsCatalogQueried,
)
from products.data_catalog.evals.seeders import (
    seed_ambiguous_top_customers_metrics,
    seed_approved_metric,
    seed_drifted_metric,
    seed_failing_top_customers_metric,
    seed_metric_listing_catalog,
    seed_proposed_metric,
    seed_top_customers_metric,
)
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext


async def eval_governed_metrics(ctx: EvalContext) -> None:
    """Does the agent use (and correctly trust) the governed-metrics catalog?"""
    cases: list[SandboxedEvalCase] = [
        # Approved metric exists: the catalog must be consulted before deriving, and the
        # runner must preserve the approved definition's personal/free exclusion.
        SandboxedEvalCase(
            name="governed_metric_approved",
            prompt="What's our MRR right now?",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_answer": {},
                "canonical_metric_run": {
                    "metric_name": APPROVED_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found the approved metric '{APPROVED_METRIC_NAME}' in the governed catalog, recognized "
                        "its trailing-30-day paid_bill semantics and personal/free exclusion, ran it through "
                        "data-catalog-metric-run, rechecked the runner's approved and non-drifted response, cited "
                        "it as the canonical definition, and reported the resulting number."
                    )
                },
            },
            setup=seed_approved_metric,
        ),
        # Synonym/derived measure: the prompt asks for "ARR", which appears in no prompt or
        # metric name — only the approved MRR metric is seeded. Tests semantic routing (the
        # "no keyword stuffing" requirement): the agent must associate ARR with the stored MRR
        # metric, run it canonically, then annualize and label the ARR figure noncanonical.
        SandboxedEvalCase(
            name="governed_metric_synonym",
            prompt="What's our ARR?",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_answer": {},
                "canonical_metric_run": {
                    "metric_name": APPROVED_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Recognized that ARR (annual recurring revenue) is the annualized form of the approved "
                        f"metric '{APPROVED_METRIC_NAME}' even though 'ARR' and 'annual' appear in neither its name "
                        "nor its description; found it via a name+description catalog search rather than deriving "
                        "revenue from scratch; ran it through data-catalog-metric-run; rechecked the runner's "
                        "approved and non-drifted response; derived ARR by annualizing the canonical MRR (x12); and "
                        "labeled the ARR figure as a noncanonical derivation of the canonical MRR metric."
                    )
                },
            },
            setup=seed_approved_metric,
        ),
        # `exec search` now returns matching governed metrics in its output, so the agent can
        # discover the metric from the search result — no execute-sql catalog query needed —
        # and run it. Credits the search-surfaced catalog lookup (scorers.py) then the run.
        SandboxedEvalCase(
            name="governed_metric_search_first",
            prompt="Search for our revenue metric and give me the current value.",
            expected={
                "metrics_catalog_queried": {},
                "canonical_metric_run": {
                    "metric_name": APPROVED_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Discovered the approved metric '{APPROVED_METRIC_NAME}' via a catalog search (either the "
                        "governed_metrics returned by exec search or a system.information_schema.metrics query), ran "
                        "it through data-catalog-metric-run rather than re-deriving revenue, rechecked the runner's "
                        "approved and non-drifted response, and reported the canonical value."
                    )
                },
            },
            setup=seed_approved_metric,
        ),
        SandboxedEvalCase(
            name="governed_metric_implicit_ranking",
            prompt="give me the top 10 B2C customers by revenue and tell me which tool you used.",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {
                    "metric_name": TOP_CUSTOMERS_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found the approved, non-drifted metric '{TOP_CUSTOMERS_METRIC_NAME}' before any schema or "
                        "raw-data discovery; recognized that it owns the B2C mapping and last-full-calendar-month "
                        "semantics; ran it with data-catalog-metric-run; rechecked the runner's approved and "
                        "non-drifted response; reported its top-10 result; and named data-catalog-metric-run as the "
                        "tool used. It must not substitute the monthly_bill_usd snapshot path."
                    )
                },
            },
            setup=seed_top_customers_metric,
        ),
        SandboxedEvalCase(
            name="governed_metric_ambiguous",
            prompt="give me the top 10 B2C customers by revenue.",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"outcome": "not_called"},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found both approved, non-drifted candidates '{TOP_CUSTOMERS_METRIC_NAME}' and "
                        f"'{CURRENT_TOP_CUSTOMERS_METRIC_NAME}', noticed their materially different time semantics "
                        "(last full calendar month versus current billing snapshot), asked the user which meaning "
                        "they want, and did not call data-catalog-metric-run or query raw data."
                    )
                },
            },
            setup=seed_ambiguous_top_customers_metrics,
        ),
        SandboxedEvalCase(
            name="governed_metric_runner_failure",
            prompt=(
                "give me the top 10 B2C customers by revenue. If the preferred calculation fails, use the best "
                "available fallback and explain what happened."
            ),
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {
                    "metric_name": TOP_CUSTOMERS_METRIC_NAME,
                    "outcome": "failed",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found the approved, non-drifted metric '{TOP_CUSTOMERS_METRIC_NAME}' before data "
                        "discovery and attempted it with data-catalog-metric-run; disclosed that the canonical run "
                        "failed; then provided a best-effort raw fallback only if it was clearly labeled "
                        "noncanonical. A fallback preserving the governed B2C and last-full-calendar-month paid-bill "
                        "semantics is preferred; if it used monthly_bill_usd instead, it explained that the "
                        "current-snapshot semantics differ."
                    )
                },
            },
            setup=seed_failing_top_customers_metric,
        ),
        # Only a proposed metric exists: derive independently; noting the proposal is fine,
        # presenting it as official is not.
        SandboxedEvalCase(
            name="governed_metric_proposed_only",
            prompt="What's our activation rate? Is there an approved company definition I should be using?",
            expected={
                "metrics_catalog_queried": {},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Checked the catalog, found only the proposed (unapproved) metric '{PROPOSED_METRIC_NAME}', "
                        "said clearly that no approved definition exists, and derived activation itself. It may "
                        "mention the proposed definition exists, but must not present that proposed metric or its "
                        "output as the approved/official answer."
                    )
                },
            },
            setup=seed_proposed_metric,
        ),
        # Approved but drifted: drift disqualifies the metric from being canonical.
        SandboxedEvalCase(
            name="governed_metric_drifted",
            prompt="Do we have an official weekly active users metric? Give me the current number.",
            expected={
                "metrics_catalog_queried": {},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found '{DRIFTED_METRIC_NAME}' in the catalog but noticed it is drifted (is_drifted=true), "
                        "did not treat its stored definition or values as authoritative, derived the number "
                        "itself, and flagged the drift instead of citing the metric as official."
                    )
                },
            },
            setup=seed_drifted_metric,
        ),
        # Listing question with decoy insights present: "what metrics are available" is a
        # catalog listing, not an insight search — the trap this case guards against.
        SandboxedEvalCase(
            name="metric_listing",
            prompt="What are the metrics that I have available in PostHog?",
            expected={
                "metrics_catalog_queried": {},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Answered from the governed-metrics catalog: listed '{APPROVED_METRIC_NAME}' as approved "
                        f"and '{PROPOSED_METRIC_NAME}' as proposed/unapproved, distinguishing the two statuses. "
                        f"It must not answer the question with saved insights (e.g. "
                        f"{', '.join(repr(name) for name in DECOY_INSIGHT_NAMES)}) as if insights were the "
                        "available metrics; mentioning them as separate saved insights is acceptable."
                    )
                },
            },
            setup=seed_metric_listing_catalog,
        ),
        # Empty catalog — the normal case: derive without stalling. Consulting the catalog is
        # allowed (and finding nothing is fine), so only the judge grades this case.
        SandboxedEvalCase(
            name="governed_metric_empty_catalog",
            prompt="What's our net revenue retention looking like?",
            expected={
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        "Produced a derivation or a clearly-reasoned approximation of net revenue retention from "
                        "the project's events without stalling: it must not ask the user to define or approve a "
                        "metric first, and must not claim it is blocked because no governed definition exists."
                    )
                },
            },
        ),
        # Raw event/property exploration with an approved metric present as temptation must
        # keep its schema-first route and skip the catalog entirely.
        SandboxedEvalCase(
            name="adhoc_no_catalog_detour",
            prompt="Break down uploaded_file events by file_type over the last 30 days.",
            expected={"metrics_catalog_not_queried": {}},
            setup=seed_approved_metric,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-governed-metrics-cli",
        cases=cases,
        scorers=[
            MetricsCatalogQueried(),
            MetricsCatalogBeforeAnswer(),
            MetricsCatalogBeforeDataDiscovery(),
            CanonicalMetricRun(),
            MetricsCatalogNotQueried(),
            GovernedBehaviorCorrectness(),
        ],
        ctx=ctx,
    )
