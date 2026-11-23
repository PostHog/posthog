"""Analysis diligence evals: does the agent verify the premise, flag anomalies, and test hypotheses?

Each case plants one truth from the scenario pack (``scenario_synthesizer.py``) and pairs a
deterministic check on the tool chain with a judge on the answer. The two midchain cases seed
governed metrics instead, and grade that the agent uses them inside a larger task.
The two no-metric cases seed only metrics that do not fit, so the agent must check the catalog, find no
match, and then define the measure itself.

To run the suite, once per surface:

    ./bin/hogli evals eval_analysis_diligence --surface app --skill-delivery bundled --provider modal
    ./bin/hogli evals eval_analysis_diligence --surface mcp --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import (
    seed_catalog_for_board_update,
    seed_catalog_noise_only,
    seed_pricing_metrics,
)
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    MRR_METRIC,
    PAYING_CUSTOMERS_METRIC,
)
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scenario_seeder import (
    seed_flat_wau,
    seed_health_check_mix,
    seed_mcp_tool_shipped,
    seed_org_grain_metric,
    seed_preview_adoption,
    seed_revenue_rep_outlier,
    seed_share_dau,
    seed_share_drop_flag,
    seed_slack_pretax_note,
    seed_upload_double_count,
    seed_wau_bot_spike,
    seed_wau_spike_with_annotation,
)
from products.data_catalog.evals.scenario_synthesizer import (
    CAMPAIGN_ANNOTATION_CONTENT,
    CAMPAIGN_UTM_SOURCE,
    CRM_OUTLIER_REP_NAME,
    MCP_EXPORT_FIRST_SEEN_DAYS_AGO,
    MCP_EXPORT_TOOL,
    MCP_SHARE_TOOL,
    ORG_GRAIN_METRIC_NAME,
    POST_TAX_MULTIPLIER,
    PREVIEW_EVENT,
    PREVIEW_FIRST_SEEN_DAYS_AGO,
    SHARE_DAU_DAILY_SHARERS,
    SHARE_FLAG_KEY,
    UPLOAD_DUPLICATE_LIB_VERSION,
    WAU_BOT_BROWSER,
    build_revenue_rep_outlier,
    build_slack_export,
    crm_deals_table,
)
from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    MetricFound,
    MetricsCatalogBeforeDataDiscovery,
    MetricsCatalogQueried,
    SemanticLayerAnswer,
)
from products.data_catalog.evals.scorers_analysis import (
    AnalysisDiligence,
    AnnotationsRead,
    AnomalyFlagged,
    AnswerCorrectness,
    ContextApplied,
    EvidenceQueried,
    FirstSeenChecked,
    SurfacesAllFindingsWhenListed,
    VerifiedBeforeExplaining,
)
from products.data_catalog.evals.seeders import synced_table_names
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import SourcesConsulted

# The spike is 8 to 10 days old, so "last week" alone could point to a window without it.
_SPIKE_PROMPT = "Check the spike in WAU over the last two weeks, what caused it?"

# A query that measures active users over time, typed or SQL.
_ACTIVE_USERS_MEASURE = (
    r"weekly_active|dau|wau|count\s*\(\s*distinct|uniq\w*\s*\(|\"math\"\s*:\s*\"(dau|weekly_active|unique)"
)
# A query that breaks traffic down by a candidate cause of the change.
_SPIKE_CAUSE = r"referr|utm_|\$browser|\$device_type|\$pathname|\$current_url|mariustechtips|\$os\b"

_CRM_TABLE = synced_table_names(crm_deals_table(build_revenue_rep_outlier()).table_name)
_SLACK_TABLE = synced_table_names(build_slack_export().table.table_name)


async def eval_analysis_diligence(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="right_data_slack_table",
            prompt="What's the average monthly spend per paying user?",
            expected={
                "sources_consulted": {"tables": [_SLACK_TABLE]},
                "context_applied": {
                    "context": (
                        "The team's Slack export says paid_bill.amount_usd is pre-tax and finance reports "
                        f"post-tax (x{POST_TAX_MULTIPLIER}). The answer must say the figure is pre-tax or "
                        "convert it to post-tax."
                    )
                },
            },
            setup=seed_slack_pretax_note,
        ),
        SandboxedEvalCase(
            name="context_grain_mismatch",
            prompt="What's the average spend per user?",
            expected={
                "metric_describe_called": {"tools": ["metric-describe"]},
                "analysis_diligence": {
                    "expected_behavior": (
                        f"Find the approved metric {ORG_GRAIN_METRIC_NAME}, read its definition, and say that it "
                        "measures spend per account, not per user. Either derive spend per user from paid_bill "
                        "events and label it as a derivation, or ask which grain the user means. Do not present "
                        "the per-account metric as the per-user answer."
                    )
                },
            },
            setup=seed_org_grain_metric,
        ),
        SandboxedEvalCase(
            name="verify_spike_exists",
            prompt=_SPIKE_PROMPT,
            expected={
                "verified_before_explaining": {"measure": _ACTIVE_USERS_MEASURE, "cause": _SPIKE_CAUSE},
                "annotations_read": {"content": CAMPAIGN_ANNOTATION_CONTENT},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Confirm in the data that weekly active users rose sharply about 8 to 10 days ago. "
                        f"Cite the project annotation '{CAMPAIGN_ANNOTATION_CONTENT}' as a lead, then verify it: "
                        f"the new users arrived on the /mariustechtips/ landing page from YouTube with "
                        f"utm_source={CAMPAIGN_UTM_SOURCE}, most signed up, and many logged in again on later days."
                    )
                },
            },
            setup=seed_wau_spike_with_annotation,
        ),
        SandboxedEvalCase(
            name="verify_spike_is_bots",
            prompt=_SPIKE_PROMPT,
            expected={
                "verified_before_explaining": {
                    "measure": _ACTIVE_USERS_MEASURE,
                    "cause": _SPIKE_CAUSE,
                    "required": True,
                },
                "anomaly_flagged": {
                    "anomaly": (
                        f"The extra weekly actives are anonymous visitors on {WAU_BOT_BROWSER} with device type "
                        "Other, who only view the home, pricing, and signup pages and never log in. This is bot "
                        "traffic. The answer must not report it as user growth."
                    )
                },
            },
            setup=seed_wau_bot_spike,
        ),
        SandboxedEvalCase(
            name="verify_no_spike",
            prompt=_SPIKE_PROMPT,
            expected={
                "claim_measured": {"patterns": [_ACTIVE_USERS_MEASURE]},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Measure weekly active users over recent weeks and report that there is no spike: WAU "
                        "stays within a few percent from week to week. Do not invent a cause for a change that "
                        "the data does not show."
                    )
                },
            },
            setup=seed_flat_wau,
        ),
        SandboxedEvalCase(
            name="anomaly_top_sales_reps",
            prompt="Who are our 5 most successful sales people over the last 12 months? Use our CRM deals export.",
            expected={
                "sources_consulted": {"tables": [_CRM_TABLE]},
                "anomaly_flagged": {
                    "anomaly": (
                        f"{CRM_OUTLIER_REP_NAME} ranks first only because of one deal about 9 times larger than "
                        "any other deal, and that deal appears twice in the export with the same deal_id. Without "
                        f"the outlier and its duplicate, {CRM_OUTLIER_REP_NAME} is not in the top 5. The answer "
                        "must flag the outlier and the duplicate before it presents a final ranking."
                    )
                },
            },
            setup=seed_revenue_rep_outlier,
        ),
        SandboxedEvalCase(
            name="hypothesis_tracking_bug",
            prompt="Why did file uploads increase last week?",
            expected={
                "hypothesis_evidence_queried": {
                    "patterns": [
                        r"\$lib_version",
                        r"\$lib\b",
                        r"duplicat",
                        r"having\s+count",
                        r"count\s*\(\s*\)\s*>\s*1",
                        r"uniq\w*\s*\(\s*(distinct_id|timestamp)",
                    ]
                },
                "analysis_diligence": {
                    "expected_behavior": (
                        "Find that uploaded_file events roughly doubled 3 to 6 days ago while the number of "
                        "uploading users did not, and that each extra event copies an existing upload (same user, "
                        "same timestamp, same file properties) but carries $lib_version "
                        f"{UPLOAD_DUPLICATE_LIB_VERSION}. "
                        "Conclude that this is a tracking bug in a client release, not more uploads."
                    )
                },
            },
            setup=seed_upload_double_count,
        ),
        SandboxedEvalCase(
            name="hypothesis_flag_block",
            prompt="Why did file shares drop last week?",
            expected={
                "hypothesis_evidence_queried": {
                    "patterns": [r"\$feature_flag", SHARE_FLAG_KEY],
                    "tools": ["feature-flag-get-all", "feature-flag-get-definition", "feature-flag-list"],
                },
                "analysis_diligence": {
                    "expected_behavior": (
                        f"Find that shared_file_link events dropped from about 9 days ago, that the users who "
                        f"stopped sharing all got the '{SHARE_FLAG_KEY}' flag with the 'blocked' variant at the "
                        "same time, and that they still log in. Conclude that the flag blocks sharing, not that "
                        "users lost interest."
                    )
                },
            },
            setup=seed_share_drop_flag,
        ),
        SandboxedEvalCase(
            name="hypothesis_correlation",
            prompt="Why did signups increase?",
            expected={
                "claim_measured": {"patterns": [r"signed_up"]},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Confirm that signed_up events rose about 8 to 10 days ago. Offer at least two candidate "
                        "explanations, test them in the data, and rank them by evidence. The best-supported one "
                        f"is the Marius Tech Tips sponsorship: the new signups came from YouTube with "
                        f"utm_source={CAMPAIGN_UTM_SOURCE} to the /mariustechtips/ page, and an annotation marks "
                        "the launch."
                    )
                },
            },
            setup=seed_wau_spike_with_annotation,
        ),
        SandboxedEvalCase(
            name="avg_dau_no_metric",
            prompt="What's the average DAU of file sharing?",
            expected={
                "metrics_catalog_queried": {},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Check the metrics catalog and find no governed definition. State the definition used "
                        "(for example, distinct users with at least one shared_file_link event per day, averaged "
                        "over a stated date range) and give the number for that definition. For that definition "
                        f"over any range in the last 90 days, the number is about {SHARE_DAU_DAILY_SHARERS}."
                    )
                },
            },
            setup=seed_share_dau,
        ),
        SandboxedEvalCase(
            name="usage_claim_one_account",
            prompt=(
                "Anixter International says they uploaded far more files in the last 30 days than we bill them for. "
                "What do our numbers show?"
            ),
            expected={
                "metrics_catalog_queried": {},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Check the metrics catalog for an upload count before writing SQL, and base the count on the "
                        "governed definition of a file upload. Count the uploaded_file events for the Anixter "
                        "International account over the last 30 days, state the definition used, and compare it with "
                        "the claim."
                    )
                },
            },
            setup=seed_catalog_noise_only,
        ),
        SandboxedEvalCase(
            name="percentile_no_metric",
            prompt="What's the 95th percentile size of uploaded files over the last 30 days, by file type?",
            expected={
                "metrics_catalog_queried": {},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Check the metrics catalog and find that no governed metric measures file size. State the "
                        "definition used: the 95th percentile of file_size_b on uploaded_file events over the last "
                        "30 days, per file_type. Say that file_size_b is in bytes, and give the sizes in a readable "
                        "unit such as MB."
                    )
                },
            },
            setup=seed_catalog_noise_only,
        ),
        SandboxedEvalCase(
            name="size_change_no_metric",
            prompt="We're thinking of capping free accounts at 2 GB of storage. How many free accounts are over that today?",
            expected={
                "metrics_catalog_queried": {},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Check the metrics catalog and find that no governed metric measures account storage. Count "
                        "the accounts whose plan is personal/free and whose used_mb is above 2 GB. Find that used_mb "
                        "holds bytes despite its name, so the limit is about 2 billion in that property, not 2,048. "
                        "State the definition used and which value of 2 GB it applies."
                    )
                },
            },
            setup=seed_catalog_noise_only,
        ),
        SandboxedEvalCase(
            name="adoption_with_first_seen",
            prompt="What's the adoption of file previews?",
            expected={
                "first_seen_checked": {"subject": PREVIEW_EVENT},
                "answer_correctness": {
                    "expected_answer": (
                        f"The {PREVIEW_EVENT} event first appears about {PREVIEW_FIRST_SEEN_DAYS_AGO} days ago. "
                        "Since then the share of active users who preview a file grew from a few percent to "
                        "roughly a quarter. The answer reports adoption as a share of active users and states "
                        "how old the feature is."
                    )
                },
            },
            setup=seed_preview_adoption,
        ),
        SandboxedEvalCase(
            name="mcp_tool_usage_since_ship",
            prompt=f"Do agents using our MCP call {MCP_EXPORT_TOOL}? Anything interesting?",
            expected={
                "first_seen_checked": {"subject": MCP_EXPORT_TOOL},
                "analysis_diligence": {
                    "expected_behavior": (
                        f"Find that {MCP_EXPORT_TOOL} first appears in $mcp_tool_call events about "
                        f"{MCP_EXPORT_FIRST_SEEN_DAYS_AGO} days ago, and measure its usage from that date, with "
                        f"a warning that earlier periods predate it. Find that sessions that call {MCP_EXPORT_TOOL} "
                        f"call {MCP_SHARE_TOOL} about three times as often as other sessions."
                    )
                },
            },
            setup=seed_mcp_tool_shipped,
        ),
        SandboxedEvalCase(
            name="multi_finding_control",
            prompt="Give me a health check of the product this month.",
            expected={
                "claim_measured": {"patterns": [r"uploaded_file", r"shared_file_link"]},
                "surfaces_all_findings": [
                    "Weekly active users and signups spiked about 8 to 10 days ago from the Marius Tech Tips campaign",
                    "uploaded_file events doubled 3 to 6 days ago because of duplicate events from a new library "
                    "version, a tracking bug",
                    f"shared_file_link events dropped from about 9 days ago because the {SHARE_FLAG_KEY} flag "
                    "blocks sharing for most of the affected users",
                ],
            },
            setup=seed_health_check_mix,
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
    ]
    await SandboxedEval(
        experiment_name="sandboxed-analysis-diligence-cli",
        cases=cases,
        scorers=[
            SourcesConsulted(),
            EvidenceQueried(name="metric_describe_called"),
            MetricsCatalogQueried(),
            VerifiedBeforeExplaining(),
            AnnotationsRead(),
            EvidenceQueried(),
            EvidenceQueried(name="claim_measured"),
            FirstSeenChecked(),
            AnalysisDiligence(),
            ContextApplied(),
            AnomalyFlagged(),
            AnswerCorrectness(),
            SurfacesAllFindingsWhenListed(),
            MetricsCatalogBeforeDataDiscovery(),
            MetricFound(),
            CanonicalMetricRun(),
            SemanticLayerAnswer(),
        ],
        ctx=ctx,
        offline_suite=offline_suite(
            "data_catalog/eval_analysis_diligence::eval_analysis_diligence",
            metrics=[
                "sources_consulted",
                "metric_describe_called",
                "metrics_catalog_queried",
                "verified_before_explaining",
                "annotations_read",
                "hypothesis_evidence_queried",
                "claim_measured",
                "first_seen_checked",
                "analysis_diligence",
                "context_applied",
                "anomaly_flagged",
                "answer_correctness",
                "surfaces_all_findings",
                "metrics_catalog_before_data_discovery",
                "metric_found",
                "canonical_metric_run",
                "semantic_layer_answer",
            ],
        ),
    )
