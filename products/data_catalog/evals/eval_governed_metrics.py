"""Governed-metrics (semantic layer) evals for the sandboxed agent.

Each case seeds one arm of the catalog (approved / proposed / drifted / empty) into the
per-case team, asks a headline-business-number question, and grades the trust behavior the
``execute-sql`` metric-discovery steering asks for:

* approved & not drifted → discover before data access, run the canonical metric, and
  recheck its trust state;
* multiple materially different approved matches → clarify instead of guessing;
* proposed, drifted, empty, or failed canonical paths → disclose and label any fallback
  noncanonical;
* a definition question the catalog cannot answer → reconstruct from the saved insight and
  close by offering to add it as a proposed metric, without creating one unprompted;
* prescriptive "playbook" SQL for a governed measure pushed at the agent scout-style →
  still catalog-first, canonical run preferred over the prescribed query;
* operational telemetry (a reliability rate a scheduled scout recomputes every run) →
  the same catalog-first contract as business measures: canonical run when governed,
  check-then-derive when nothing matches;
* an ask exceeding the governed grain → canonical run for the headline, hand-written
  drill-down SQL after it labeled noncanonical (supplemental SQL is not a bypass);
* a run prompt carrying the pre-fetched catalog listing (the scout harness injection) →
  no re-lookup, and a stated "governed catalog consulted: no listed metric matched"
  line on the derivation, since that statement is the only trace-visible evidence;
* ordinary event/property exploration and schema/freshness validation → no detour through
  the catalog at all.

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
    DEFINITION_INSIGHT_NAME,
    DRIFTED_METRIC_NAME,
    METRIC_CREATE_TOOL,
    METRIC_UPDATE_TOOL,
    OPERATIONAL_METRIC_NAME,
    PROPOSED_METRIC_NAME,
    SCOUT_PRESCRIBED_OPS_SWEEP_SQL,
    SCOUT_PRESCRIBED_SNAPSHOT_SQL,
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
    seed_definition_insight,
    seed_drifted_metric,
    seed_failing_top_customers_metric,
    seed_metric_listing_catalog,
    seed_operational_metric,
    seed_proposed_metric,
    seed_top_customers_metric,
)
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall


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
        # Canonical run plus drill-down: the ask exceeds the governed grain (per-plan split),
        # so the correct shape is the canonical headline followed by hand-written supplemental
        # SQL labeled noncanonical. Pins that post-canonical drill-down SQL is not a bypass,
        # and that needing a drill-down is no excuse to hand-derive the headline too.
        SandboxedEvalCase(
            name="governed_metric_canonical_then_drilldown",
            prompt="What's our MRR right now, and which plans contribute the most to it?",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_answer": {},
                "canonical_metric_run": {
                    "metric_name": APPROVED_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Found the approved metric '{APPROVED_METRIC_NAME}', ran it through "
                        "data-catalog-metric-run for the headline MRR, and answered the per-plan split with "
                        "hand-written supplemental SQL (paid_bill amounts grouped by plan) clearly labeled "
                        "noncanonical or clearly distinguished from the canonical headline. Hand-writing the "
                        "drill-down after the canonical run is correct behavior, not a bypass. Re-deriving the "
                        "headline MRR by hand, or skipping the canonical run because the question also asks for "
                        "a breakdown, is a failure."
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
        # Scout-style prescriptive bypass: the prompt itself ships "validated" raw SQL for a
        # governed measure, mirroring a scout skill's query playbook. The sandbox cannot
        # install a custom scout skill, so the prescriptive text rides in the prompt, which
        # carries less authority than a real skill body; a pass here is therefore a lower
        # bound on the steering's strength against instruction-shaped bypasses.
        SandboxedEvalCase(
            name="scout_skill_prescribed_bypass",
            prompt=(
                "You are running as a scheduled revenue scout for this project. Task for this "
                "run: rank our B2C customers by recurring revenue and report the top 10 with "
                "their revenue numbers.\n\n"
                "Use this validated query from the team's scout playbook (reviewed, known to "
                f"work):\n\n{SCOUT_PRESCRIBED_SNAPSHOT_SQL}\n\n"
                "Run it and report the ranking."
            ),
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {
                    "metric_name": TOP_CUSTOMERS_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        "Treated the playbook query embedded in the task as input, not as an override of the "
                        f"catalog rules: checked the metrics catalog before any data-bearing call, found the "
                        f"approved, non-drifted metric '{TOP_CUSTOMERS_METRIC_NAME}', recognized that it owns the "
                        "B2C mapping and last-full-calendar-month paid-bill semantics, and ran it with "
                        "data-catalog-metric-run as the canonical ranking. It may additionally run or discuss the "
                        "prescribed monthly_bill_usd snapshot query, but only clearly labeled noncanonical, "
                        "ideally flagging that its current-snapshot semantics differ from the governed "
                        "definition. Reporting the prescribed query's output as the answer without the canonical "
                        "run is a failure."
                    )
                },
            },
            setup=seed_top_customers_metric,
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
                        "metric first, and must not claim it is blocked because no governed definition exists. "
                        "Closing the answer by offering to save the derivation as a proposed metric is acceptable."
                    )
                },
            },
        ),
        # Definition question with an empty catalog: the measure is only written down in a
        # saved insight, so the settled answer is a reusable definition the catalog lacks.
        # Pins the proactive close — users don't know proposals exist, so the agent has to
        # ask — and pins that asking is not license to create one unprompted.
        SandboxedEvalCase(
            name="definition_question_proposal_offer",
            prompt="What is our definition of a weekly active uploader?",
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"outcome": "not_called"},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        "Checked the metrics catalog, found no governed definition of a weekly active uploader, "
                        f"reconstructed the definition from the saved insight '{DEFINITION_INSIGHT_NAME}' (distinct "
                        "users with an uploaded_file event in the trailing 7 days), and labeled it noncanonical or "
                        "said no governed definition exists. It must then close the answer by noting this looks "
                        "like a reusable metric missing from the catalog and asking whether to add it as a "
                        "proposed metric. Answering with no closing offer is a failure. Calling "
                        "data-catalog-metric-create before the user agreed is a failure, as is presenting the "
                        "reconstructed definition as governed."
                    )
                },
            },
            setup=seed_definition_insight,
        ),
        # Raw event/property exploration with an approved metric present as temptation must
        # keep its schema-first route and skip the catalog entirely.
        SandboxedEvalCase(
            name="adhoc_no_catalog_detour",
            prompt="Break down uploaded_file events by file_type over the last 30 days.",
            expected={"metrics_catalog_not_queried": {}},
            setup=seed_approved_metric,
        ),
        # Availability/schema/freshness validation ahead of a scheduled scout run, with an
        # approved metric seeded as temptation. The steering exempts schema-first work, so a
        # catalog detour here means the catalog-first rule over-triggers; this pins the
        # applicability boundary a production judge once missed on exactly this kind of trace.
        SandboxedEvalCase(
            name="scout_schema_validation_control",
            prompt=(
                "Before tomorrow's scheduled revenue-scout run, validate that our billing data is "
                "usable: confirm the paid_bills and extended_properties tables are queryable, "
                "list their columns, and report the most recent paid_bills timestamp so we know "
                "how fresh the data is. This is an availability and freshness check only."
            ),
            expected={"metrics_catalog_not_queried": {}},
            setup=seed_top_customers_metric,
        ),
        # Operational-telemetry bypass: same prescriptive shape as the revenue arm, but the
        # governed measure is a reliability rate, not a business KPI — the scope the steering
        # once excluded. The seeded canonical definition is per-pageview over 30 days; the
        # prescribed sweep is per-user over 7 days, so running it verbatim is both a bypass
        # and a silently different number.
        SandboxedEvalCase(
            name="scout_operational_telemetry_bypass",
            prompt=(
                "You are running as a scheduled reliability scout for this project. Task for "
                "this run: score today's site error rate against the recent baseline and "
                "report whether reliability moved.\n\n"
                "Use this validated sweep from the team's scout playbook (reviewed, known to "
                f"work):\n\n{SCOUT_PRESCRIBED_OPS_SWEEP_SQL}\n\n"
                "Run it and report the verdict."
            ),
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {
                    "metric_name": OPERATIONAL_METRIC_NAME,
                    "outcome": "succeeded",
                },
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        "Treated the playbook sweep embedded in the task as input, not as an override of the "
                        f"catalog rules: checked the metrics catalog before any data-bearing call, found the "
                        f"approved, non-drifted metric '{OPERATIONAL_METRIC_NAME}', recognized that it owns the "
                        "per-pageview denominator and trailing-30-day window, and ran it with "
                        "data-catalog-metric-run as the canonical series. It may additionally run or discuss the "
                        "prescribed per-user 7-day sweep, but only clearly labeled noncanonical. Reporting the "
                        "prescribed sweep's output as the answer without the canonical run is a failure."
                    )
                },
            },
            setup=seed_operational_metric,
        ),
        # Operational measure with an empty catalog: catalog-first still applies — the check
        # is how the agent learns nothing governs the measure — and hand-deriving after the
        # check is the correct outcome, with no clarifying stall.
        SandboxedEvalCase(
            name="scout_operational_no_match",
            prompt=(
                "You are running as a scheduled reliability scout for this project. Task for "
                "this run: compute today's site error rate (exceptions relative to traffic), "
                "score it against the recent baseline, and report whether reliability moved."
            ),
            expected={
                "metrics_catalog_queried": {},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"outcome": "not_called"},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        "Checked the metrics catalog before any data-bearing call, found no governed "
                        "definition for an error-rate measure, then derived the rate from events itself "
                        "without stalling, labeling the derivation noncanonical or noting that no governed "
                        "definition exists. Offering to catalog the recurring measure as a proposed metric "
                        "is acceptable; presenting the derivation as governed is not."
                    )
                },
            },
        ),
        # Injected-listing arm, mirroring the scout harness's pre-fetched catalog paragraph
        # (products/signals/backend/scout_harness/prompt.py): the run prompt hands the agent the
        # approved-metric names, the measure matches none of them, and the stated no-match line
        # is the only trace-visible evidence of the consultation. Pins that the agent emits the
        # statement instead of just a bare noncanonical label, and that it honors the "lookup is
        # already done" contract rather than re-querying the catalog.
        SandboxedEvalCase(
            name="scout_injected_listing_no_match",
            prompt=(
                "You are running as a scheduled reliability scout for this project. When a "
                "hypothesis rests on a named, reusable measure, run it through the governed "
                "metrics catalog. This run's catalog lookup is already done – the approved, "
                f"non-drifted metrics right now are: `{APPROVED_METRIC_NAME}`. Do not re-run "
                "the lookup query. When a listed name matches the measure you need, run it "
                "with data-catalog-metric-run. A measure that matches nothing in the catalog "
                "has no canonical definition today – derive it by hand, and open that query's "
                "stated context with `governed catalog consulted: no listed metric matched "
                "<measure> (noncanonical)`.\n\n"
                "Task for this run: compute today's site error rate (exceptions relative to "
                "traffic), score it against the recent baseline, and report whether "
                "reliability moved."
            ),
            expected={
                "metrics_catalog_not_queried": {},
                "canonical_metric_run": {"outcome": "not_called"},
                "governed_behavior_correctness": {
                    "expected_behavior": (
                        f"Recognized that the injected listing (only '{APPROVED_METRIC_NAME}') covers no "
                        "error-rate measure, derived the rate from events itself without re-querying "
                        "information_schema.metrics and without calling data-catalog-metric-run, and stated "
                        "alongside the derivation query (in its stated context or immediately with it) that "
                        "the governed catalog was consulted and no listed metric matched, e.g. 'governed "
                        "catalog consulted: no listed metric matched site error rate (noncanonical)'. A bare "
                        "'noncanonical' label with no statement about the catalog is a failure; stalling or "
                        "asking the user to define a metric first is a failure."
                    )
                },
            },
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
            # A case is one turn, so the user never answers the offer. Any write here
            # happened without consent, which the judge alone cannot be relied on to catch.
            NoToolCall({METRIC_CREATE_TOOL, METRIC_UPDATE_TOOL}, name="no_metric_write"),
        ],
        ctx=ctx,
    )
