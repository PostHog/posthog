"""Analysis diligence evals: does the agent verify the premise, flag anomalies, and test hypotheses?

Each case plants one truth from the scenario pack (``scenario_synthesizer.py``) and pairs a
deterministic check on the tool chain with a judge on the answer.

To run the suite, once per surface:

    EVAL_SURFACE=app ./bin/hogli evals eval_analysis_diligence --skill-delivery bundled --provider modal
    EVAL_SURFACE=mcp ./bin/hogli evals eval_analysis_diligence --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scenario_seeder import (
    seed_health_check_mix,
    seed_mcp_tool_shipped,
    seed_org_grain_metric,
    seed_preview_adoption,
    seed_revenue_rep_outlier,
    seed_share_drop_flag,
    seed_slack_pretax_note,
    seed_upload_double_count,
    seed_wau_bot_spike,
    seed_wau_spike_with_annotation,
    table_aliases,
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
    SHARE_FLAG_KEY,
    UPLOAD_DUPLICATE_LIB_VERSION,
    WAU_BOT_BROWSER,
    build_revenue_rep_outlier,
    build_slack_export,
    crm_deals_table,
)
from products.data_catalog.evals.scorers import MetricsCatalogQueried
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
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import SourcesConsulted

_SPIKE_PROMPT = "Check the spike in WAU last week, what caused it?"

# A query that measures active users over time, typed or SQL.
_ACTIVE_USERS_MEASURE = (
    r"weekly_active|dau|wau|count\s*\(\s*distinct|uniq\w*\s*\(|\"math\"\s*:\s*\"(dau|weekly_active|unique)"
)
# A query that breaks traffic down by a candidate cause of the change.
_SPIKE_CAUSE = r"referr|utm_|\$browser|\$device_type|\$pathname|\$current_url|mariustechtips|\$os\b"

_CRM_TABLE = table_aliases(crm_deals_table(build_revenue_rep_outlier()))
_SLACK_TABLE = table_aliases(build_slack_export().table)


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
                "annotations_read": {},
                "analysis_diligence": {
                    "expected_behavior": (
                        "Confirm in the data that weekly active users rose sharply about 8 to 10 days ago. "
                        f"Cite the project annotation '{CAMPAIGN_ANNOTATION_CONTENT}' as a lead, then verify it: "
                        f"the new users arrived on the /mariustechtips/ landing page from YouTube with "
                        f"utm_source={CAMPAIGN_UTM_SOURCE}, signed up, and logged in again on later days."
                    )
                },
            },
            setup=seed_wau_spike_with_annotation,
        ),
        SandboxedEvalCase(
            name="verify_spike_is_bots",
            prompt=_SPIKE_PROMPT,
            expected={
                "verified_before_explaining": {"measure": _ACTIVE_USERS_MEASURE, "cause": _SPIKE_CAUSE},
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
                        "Measure weekly active users over recent weeks and report that there is no spike last "
                        "week. Do not invent a cause for a change that the data does not show."
                    )
                },
            },
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
                        "uploading users did not, that the extra events are exact duplicates (same user, same "
                        f"timestamp, same properties), and that they carry $lib_version {UPLOAD_DUPLICATE_LIB_VERSION}. "
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
                        "over a stated date range) and give the number for that definition."
                    )
                },
            },
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
            ],
        ),
    )
