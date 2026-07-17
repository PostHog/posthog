"""Governed-metrics (semantic layer) evals for the sandboxed agent.

Each case seeds one arm of the catalog (approved / proposed / drifted / empty) into the
per-case team, asks a headline-business-number question, and grades the trust behavior the
``execute-sql`` metric-discovery steering asks for:

* approved & not drifted → consult the catalog before answering and cite the canonical
  definition instead of re-deriving;
* proposed or drifted → derive independently, never presenting the unapproved metric as
  canonical;
* empty catalog → derive without stalling or asking the user to define a metric first;
* ordinary exploration → no detour through the catalog at all.

Prompts read like real user questions and never mention ``information_schema``. The
``metric-run`` MCP tool does not exist yet, so no scorer requires it — running the stored
definition via ``execute-sql`` counts as adopting it.

To run a single case::

    flox activate -- bash -c "hogli evals eval_governed_metrics --eval governed_metric_approved"
"""

from __future__ import annotations

from products.data_catalog.evals.constants import (
    APPROVED_METRIC_NAME,
    DECOY_INSIGHT_NAMES,
    DRIFTED_METRIC_NAME,
    PROPOSED_METRIC_NAME,
)
from products.data_catalog.evals.scorers import (
    GovernedBehaviorCorrectness,
    MetricsCatalogBeforeAnswer,
    MetricsCatalogNotQueried,
    MetricsCatalogQueried,
)
from products.data_catalog.evals.seeders import (
    seed_approved_metric,
    seed_drifted_metric,
    seed_metric_listing_catalog,
    seed_proposed_metric,
)
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext


async def eval_governed_metrics(ctx: EvalContext) -> None:
    """Does the agent use (and correctly trust) the governed-metrics catalog?"""
    cases: list[SandboxedEvalCase] = [
        # Approved metric exists: the catalog must be consulted before deriving, and the
        # approved definition (with its personal/free exclusion) adopted and cited.
        SandboxedEvalCase(
            name="governed_metric_approved",
            prompt="What's our MRR right now? If we have an official definition of it, use that.",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_answer": {},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found the approved metric '{APPROVED_METRIC_NAME}' in the governed catalog, adopted its "
                        "stored definition (a paid_bill sum over the trailing 30 days that excludes the "
                        "personal/free plan) rather than inventing one, cited it as the approved/canonical "
                        "definition, and reported the resulting number."
                    )
                },
            },
            setup=seed_approved_metric,
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
        # Ordinary exploration with an approved metric present as temptation: the catalog is
        # only for named headline numbers, so a breakdown question must skip it entirely.
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
            MetricsCatalogNotQueried(),
            GovernedBehaviorCorrectness(),
        ],
        ctx=ctx,
    )
