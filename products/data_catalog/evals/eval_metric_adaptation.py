"""Metric adaptation evals: change a governed metric to fit the question, and keep what it measures.

The MRR cases adapt a HogQL metric in SQL. The trends and funnel cases adapt a typed metric, so the adapted
query must stay a typed query: ``insight_shape`` checks that the answer ran ``query-trends`` or
``query-funnel`` with the metric's measure plus the requested change. The ``sql_from_typed_*`` cases ask for
a shape no typed runner returns, so the agent must carry the typed metric's definition of an active
account into SQL. ``insight_shape`` does not grade them, because it prefers any typed query over SQL as the
answer, and an agent can correctly run the trends headline before it writes the SQL.

Run it once per surface:

    ./bin/hogli evals eval_metric_adaptation --surface app --skill-delivery bundled --provider modal
    ./bin/hogli evals eval_metric_adaptation --surface mcp --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import (
    seed_account_engagement_metric,
    seed_activation_funnel_metric,
    seed_catalog_for_account_check_in,
    seed_catalog_for_account_spend,
    seed_catalog_with_account_engagement,
    seed_catalog_with_churned_accounts,
    seed_catalog_with_mrr,
    seed_catalog_with_paying_customers,
    seed_mrr_metric,
)
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    ACTIVATION_FUNNEL_METRIC,
    CHURN_RISK_METRIC,
    CHURNED_ACCOUNTS_METRIC,
    MRR_DISTINGUISHING_TERMS,
    MRR_METRIC,
    PAYING_CUSTOMERS_METRIC,
    TOOL_FAILURE_RATE_METRIC,
)
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scenario_seeder import seed_mcp_tool_failures, seed_tool_failures_in_catalog
from products.data_catalog.evals.scenario_synthesizer import MCP_FAILING_TOOL, MCP_FAILURE_RISE_DAYS
from products.data_catalog.evals.scorers import (
    MetricDescribeBeforeAdaptedSql,
    MetricFound,
    NoDataSqlRun,
    QueryTermsUsed,
    RunOverrideUsed,
    SemanticLayerAnswer,
)
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.product_analytics.scorers import InsightShape

_ADAPTED_MRR = {
    "metric_describe_before_adapted_sql": {},
    "query_terms_used": {"terms": list(MRR_DISTINGUISHING_TERMS)},
}


# One account's spend keeps the MRR measure and adds the account group key, which is how bills attach to accounts.
_ONE_ACCOUNT_MRR = {
    "metric_describe_before_adapted_sql": {},
    "query_terms_used": {"terms": ["paid_bill", "$group_0"]},
}


_WEEKLY_ACCOUNTS = {"tool": "query-trends", "math": ["unique_group"], "interval": "week"}


def _adapted_typed_behavior(metric_name: str, change: str, keep: str) -> str:
    return (
        f"Find {metric_name} in the catalog and read its definition with metric-describe. Adapt that stored "
        f"query to {change}, keep {keep}, and run it with the typed query runner of its kind, not with "
        "hand-written SQL. Report the values the run returned. Label the result as an adaptation of the "
        "governed metric, not as the approved number itself."
    )


# The governed definition of an active account: any event that carries the account group key.
_ACTIVE_ACCOUNT_TERMS = ["$group_0"]


def _sql_from_typed_behavior(shape: str) -> str:
    return (
        f"Find {ACCOUNT_ENGAGEMENT_METRIC.name} in the catalog and read its definition with metric-describe. "
        "No typed query runner returns this shape, so write SQL that keeps the metric's definition: an active "
        f"account is a distinct account group key on any event in the window. Return {shape}. Label the result "
        "as derived from the governed metric, not as the approved number itself."
    )


def _churned_accounts_behavior(change: str) -> str:
    return (
        f"Find {CHURNED_ACCOUNTS_METRIC.name} in the catalog and read its definition with metric-describe. Adapt "
        f"that stored query to {change}, and keep its definition of a churned account: active in the 60 days before "
        "the last 30 days, with no activity in the last 30 days, keyed by $group_0. Label the result as an "
        "adaptation of the governed metric, not as the approved number itself."
    )


_CHURNED_ACCOUNTS = {
    "metric_found": {"metric_name": CHURNED_ACCOUNTS_METRIC.name},
    "metric_describe_before_adapted_sql": {},
    "query_terms_used": {"terms": ["$group_0"]},
}

# The governed definition reads the paid_bills warehouse table, not paid_bill events, so an adapted query must too.
_PAYING_CUSTOMERS_LOOKUP = {
    "metric_found": {"metric_name": PAYING_CUSTOMERS_METRIC.name},
    "query_terms_used": {"terms": ["paid_bills"]},
}
_PAYING_CUSTOMERS = {**_PAYING_CUSTOMERS_LOOKUP, "metric_describe_before_adapted_sql": {}}

# The canvas suggestion template from products/today/frontend/spaces/newSessionSuggestionDefaults.ts.
_CANVAS_TEMPLATE = (
    "Research a question about our product, then build a canvas that explains the answer. Include the charts that "
    "show it and short written context for what they mean.\n\n\nUser input:\n"
    "- What should the canvas explain: {topic}\n"
    "- Time period (optional): {period}"
)

_DOWNLOADING_ACCOUNTS_SQL = (
    "SELECT toStartOfMonth(timestamp) AS month, count(DISTINCT $group_0) AS accounts\n"
    "FROM events\n"
    "WHERE event = 'downloaded_file'\n"
    "GROUP BY month\n"
    "ORDER BY month"
)


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
                # A query grouped by plan answers it too, and that SQL never names business/. A group-by on
                # any other column keeps every plan in one total, so it does not count.
                "query_terms_used": {
                    "terms": ["paid_bill", ["business/", "group by plan", "group by properties.plan"]]
                },
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
        SandboxedEvalCase(
            name="adjust_one_account_spend",
            prompt="How much did our biggest paying account pay us over the last 30 days?",
            expected={
                **_ONE_ACCOUNT_MRR,
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "find the account with the largest paid_bill total in the window, and report that "
                        "account's total"
                    )
                },
            },
            setup=seed_mrr_metric,
        ),
        SandboxedEvalCase(
            name="adjust_one_account_annual_value",
            prompt="What's our top paying account worth per year at its current spend?",
            expected={
                **_ONE_ACCOUNT_MRR,
                "semantic_layer_answer": {
                    "expected_behavior": (
                        _adapted_mrr_behavior(
                            "find the account with the largest paid_bill total in the window, and report that "
                            "account's total"
                        )
                        + " Multiply that 30-day total by 12 for the yearly value, and say that the yearly value "
                        "is an estimate derived from the governed metric."
                    )
                },
            },
            setup=seed_mrr_metric,
        ),
        SandboxedEvalCase(
            name="adjust_compare_to_past_window",
            prompt="Our goal is to grow MRR by 20% this quarter. How are we tracking against 60 days ago?",
            expected={
                **_ADAPTED_MRR,
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "compute the same 30-day total for the window that ended 60 days ago, next to the current "
                        "value, and compare the growth with the 20% goal"
                    )
                },
            },
            setup=seed_mrr_metric,
        ),
        SandboxedEvalCase(
            name="adapt_failure_rate_for_one_tool",
            prompt=f"Is the {MCP_FAILING_TOOL} tool failing more often this past week than before?",
            expected={
                "metric_found": {"metric_name": TOOL_FAILURE_RATE_METRIC.name},
                "metric_describe_before_adapted_sql": {},
                "query_terms_used": {"terms": ["$mcp_is_error", MCP_FAILING_TOOL]},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {TOOL_FAILURE_RATE_METRIC.name} in the catalog and read its definition with "
                        f"metric-describe. Adapt that stored query to count only {MCP_FAILING_TOOL} calls and to "
                        f"compare the last {MCP_FAILURE_RISE_DAYS} days with the three weeks before, and keep the "
                        "$mcp_is_error failure flag on $mcp_tool_call events. Report that the failure share rose from "
                        "about 5% to about a third in the last week. Label the result as an adaptation of the "
                        "governed metric, not as the approved number itself."
                    )
                },
            },
            setup=seed_mcp_tool_failures,
        ),
        # The next four cases add the noise catalog, because an agent skips the catalog more often when the
        # question names an account or a task rather than the measure.
        SandboxedEvalCase(
            name="adjust_one_account_annual_plan_savings",
            prompt="How much would Anixter International save in a year by moving to an annual plan with 20% off what they pay now?",
            expected={
                **_ONE_ACCOUNT_MRR,
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "the Anixter International account through $group_0, then multiply that 30-day total by 12 "
                        "and take 20% of it as the yearly saving"
                    )
                },
            },
            setup=seed_catalog_with_mrr,
        ),
        SandboxedEvalCase(
            name="adjust_one_account_revenue_at_risk",
            prompt=(
                "Anixter International told their account manager they may move their files to an in-house system. "
                "What else do they use us for, and how much revenue would we lose if they left?"
            ),
            expected={
                **_ONE_ACCOUNT_MRR,
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "the Anixter International account through $group_0 to size the revenue at risk"
                    )
                    + " Also describe what else the account does in the product."
                },
            },
            setup=seed_catalog_with_mrr,
        ),
        SandboxedEvalCase(
            name="adjust_mrr_band_account_list",
            prompt=(
                "I want to interview 15 users from accounts that pay between $10 and $50 a month and that logged in "
                "during the last 14 days. List them with their account, how many days they were active in the last "
                "30 days, and when they signed up."
            ),
            expected={
                **_ONE_ACCOUNT_MRR,
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_mrr_behavior(
                        "a 30-day total per account through $group_0, and keep only accounts between $10 and $50"
                    )
                    + " Then list users of those accounts who logged in during the last 14 days, with active days in "
                    "the last 30 days and the signup date."
                },
            },
            setup=seed_catalog_with_mrr,
        ),
        SandboxedEvalCase(
            name="adjust_mrr_month_projection",
            prompt=(
                "Where will MRR land for the current month? Check first whether this month's data is complete so "
                "far, and tell me which base you used for the projection."
            ),
            expected={
                "metric_describe_before_adapted_sql": {},
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {MRR_METRIC.name} in the catalog and read its definition with metric-describe. Keep the "
                        "paid_bill event and the personal/free exclusion, but replace the 30-day window with the "
                        "current calendar month so far. Check how many of the month's days have data, project the "
                        "full month from that base, and label the projection as an adaptation of the governed MRR "
                        "metric, not as the approved number itself."
                    )
                },
            },
            setup=seed_catalog_with_mrr,
        ),
        # The next eight cases name an account, a screen, or a group of accounts, but not the governed measure.
        SandboxedEvalCase(
            name="adjust_one_account_bill_increase",
            prompt=(
                "Anixter International's bill went up. Which part of their usage caused it, and when did it "
                "start? Also, how many people at Anixter International used Hedgebox in the last 30 days?"
            ),
            expected={
                **_ONE_ACCOUNT_MRR,
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {MRR_METRIC.name} in the catalog and read its definition with metric-describe. Adapt "
                        "it to the Anixter International account through $group_0, and keep the paid_bill event "
                        "and the personal/free exclusion, with one total per month instead of one 30-day total. "
                        "Find that the account pays the same amount every month, so the data does not show a "
                        "higher bill, and say so instead of naming a cause. Report that one person at the account "
                        "was active in the last 30 days. Label the figures as adaptations of the governed metric."
                    )
                },
            },
            setup=seed_catalog_for_account_spend,
        ),
        SandboxedEvalCase(
            name="adapt_one_account_feature_use",
            prompt="Does Anixter International use file downloads, file uploads, or team invites? How much of each?",
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "query_terms_used": {"terms": ["$group_0"]},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {ACCOUNT_ENGAGEMENT_METRIC.name} in the catalog and use its account key, the "
                        "$group_0 account group, to scope the counts to Anixter International. Report the account's "
                        "downloaded_file, uploaded_file, and invited_team_member counts with a time window. Find "
                        "that downloads and invites recur, and that the account uploaded a file only once, soon "
                        "after it signed up."
                    )
                },
            },
            setup=seed_catalog_with_account_engagement,
        ),
        SandboxedEvalCase(
            name="adapt_one_account_churn_check",
            prompt=(
                "Can you look into Anixter International for me? They complained about what their plan costs, and "
                "I want to know if they are about to leave."
            ),
            expected={
                "metric_found": {"metric_name": CHURN_RISK_METRIC.name},
                "query_terms_used": {"terms": ["$group_0"]},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {CHURN_RISK_METRIC.name} in the catalog, read its steps with metric-describe, and "
                        "apply both conditions to the Anixter International account: a downgraded_plan event in the "
                        "last 60 days, or 3 or more deleted_file events in the last 30 days. Find that neither "
                        "condition holds, so the governed definition does not flag the account. Support this with "
                        f"the account's bills from {MRR_METRIC.name}, which stay the same every month, and with "
                        "recent activity in the last few days."
                    )
                },
            },
            setup=seed_catalog_for_account_check_in,
        ),
        SandboxedEvalCase(
            name="adapt_paying_customers_who_invite",
            prompt="How many of our customers have invited a teammate?",
            expected={
                **_PAYING_CUSTOMERS,
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {PAYING_CUSTOMERS_METRIC.name} in the catalog and read its definition with "
                        "metric-describe. Use its definition of a customer, a bill in paid_bills in the last full "
                        "calendar month, and count the customers who have an invited_team_member event. State the "
                        "definition used. Label the count as an adaptation of the governed metric."
                    )
                },
            },
            setup=seed_catalog_with_paying_customers,
        ),
        SandboxedEvalCase(
            name="adapt_open_query_to_paying_customers",
            prompt=(
                "I have this query open in the SQL editor:\n\n"
                f"```sql\n{_DOWNLOADING_ACCOUNTS_SQL}\n```\n\n"
                "The count falls off in the last month. I think something changed in the data. Can you fix it and "
                "then show the same chart for paying customers only?"
            ),
            # The agent runs the user's query to check the drop before it reads the catalog, so this case
            # leaves out the scorer that wants metric-describe before any analytical SQL.
            expected={
                **_PAYING_CUSTOMERS_LOOKUP,
                "semantic_layer_answer": {
                    "expected_behavior": (
                        "Check the drop against the data before accepting that something changed: compare the "
                        "latest event date with the end of the last month in the result. The event history ends "
                        "when the demo data was generated, so the last month is incomplete. If it covers only part "
                        "of the month, say that the drop comes from the partial month, and exclude or mark that "
                        "month. If it is almost complete and shows no real drop, say so. Do not claim a data change "
                        f"that the queries do not show. Then find {PAYING_CUSTOMERS_METRIC.name} in the catalog, "
                        "read its definition with metric-describe, and keep only accounts that paid a bill in "
                        "paid_bills by that definition. State the definition used, and label the filter as an "
                        "adaptation of the governed metric."
                    )
                },
            },
            setup=seed_catalog_with_paying_customers,
        ),
        SandboxedEvalCase(
            name="adapt_failure_rate_canvas_summary",
            prompt=_CANVAS_TEMPLATE.format(
                topic="a summary of agent tool problems with the import tools", period="last 30 days"
            ),
            expected={
                "metric_found": {"metric_name": TOOL_FAILURE_RATE_METRIC.name},
                "metric_describe_before_adapted_sql": {},
                "query_terms_used": {"terms": ["$mcp_is_error", MCP_FAILING_TOOL]},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {TOOL_FAILURE_RATE_METRIC.name} in the catalog and read its definition with "
                        "metric-describe. Adapt it to a 30-day window and to the import tools, and keep the "
                        "$mcp_is_error failure flag on $mcp_tool_call events. Report that the failure share of "
                        f"{MCP_FAILING_TOOL} rose from about 5% to about a third in the last {MCP_FAILURE_RISE_DAYS} "
                        "days. Label the figures as adaptations of the governed metric."
                    )
                },
            },
            setup=seed_tool_failures_in_catalog,
        ),
        SandboxedEvalCase(
            name="adapt_churn_by_team_invites",
            prompt="Do accounts that invited a teammate churn less than accounts that never did?",
            expected={
                **_CHURNED_ACCOUNTS,
                "semantic_layer_answer": {
                    "expected_behavior": _churned_accounts_behavior(
                        "compare the churned share of accounts with an invited_team_member event against the "
                        "churned share of accounts without one"
                    )
                    + " Say that only business plans can invite team members, so plan is a confounder, and compare "
                    "within business plans too."
                },
            },
            setup=seed_catalog_with_churned_accounts,
        ),
        SandboxedEvalCase(
            name="adapt_churned_free_heavy_downloaders",
            prompt="How many free accounts with at least 20 downloads in total have stopped using Hedgebox?",
            expected={
                **_CHURNED_ACCOUNTS,
                "semantic_layer_answer": {
                    "expected_behavior": _churned_accounts_behavior(
                        "keep only accounts on the personal/free plan with 20 or more downloaded_file events over "
                        "their whole history"
                    )
                },
            },
            setup=seed_catalog_with_churned_accounts,
        ),
        SandboxedEvalCase(
            name="adapt_trend_grouping",
            prompt="Show me weekly active accounts for the last 4 weeks, split by each account's plan.",
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "insight_shape": {**_WEEKLY_ACCOUNTS, "breakdown": "plan", "date_from": ["-4w", "-28d", "-1m"]},
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_typed_behavior(
                        ACCOUNT_ENGAGEMENT_METRIC.name,
                        "break the count down by the account group's plan property",
                        "the unique-account math and the weekly interval",
                    )
                },
            },
            setup=seed_account_engagement_metric,
        ),
        SandboxedEvalCase(
            name="adapt_trend_window_and_filter",
            prompt="How many accounts were active each week over the last 8 weeks, counting only users in the US?",
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "insight_shape": {
                    **_WEEKLY_ACCOUNTS,
                    "date_from": ["-8w", "-56d", "-2m"],
                    "filtered_on": ["$geoip_country_code"],
                },
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_typed_behavior(
                        ACCOUNT_ENGAGEMENT_METRIC.name,
                        "cover the last 8 weeks and count only activity from users whose country code is US",
                        "the unique-account math and the weekly interval",
                    )
                },
            },
            setup=seed_account_engagement_metric,
        ),
        SandboxedEvalCase(
            name="adapt_funnel_breakdown_and_window",
            prompt="What's our signup activation rate by browser over the last 90 days?",
            expected={
                "metric_found": {"metric_name": ACTIVATION_FUNNEL_METRIC.name},
                "insight_shape": {
                    "tool": "query-funnel",
                    "event_sequence": ["signed_up", "uploaded_file"],
                    "funnel_window": "14 day",
                    "breakdown": "$browser",
                    "date_from": ["-90d", "-3m", "-12w", "-13w"],
                },
                "semantic_layer_answer": {
                    "expected_behavior": _adapted_typed_behavior(
                        ACTIVATION_FUNNEL_METRIC.name,
                        "cover the last 90 days and break the conversion down by $browser",
                        "the signed_up to uploaded_file steps and the 14-day conversion window",
                    )
                },
            },
            setup=seed_activation_funnel_metric,
        ),
        SandboxedEvalCase(
            name="sql_from_typed_entity_table",
            prompt=(
                "Using our definition of an active account, list every account that was active in the last 4 weeks, "
                "with its name, plan, number of uploads, number of downloads, and the date of its last activity."
            ),
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "metric_describe_before_adapted_sql": {},
                "query_terms_used": {"terms": [*_ACTIVE_ACCOUNT_TERMS, "uploaded_file", "downloaded_file", "plan"]},
                "semantic_layer_answer": {
                    "expected_behavior": _sql_from_typed_behavior(
                        "one row per active account in the last 4 weeks with its name, plan, upload count, "
                        "download count and last activity date"
                    )
                },
            },
            setup=seed_account_engagement_metric,
        ),
        SandboxedEvalCase(
            name="sql_from_typed_status_buckets",
            prompt=(
                "Using our definition of an active account, compare the last 4 weeks with the 4 weeks before. Label "
                "each account: new (first activity ever in the last 4 weeks), retained (active in both periods), "
                "returning (active in the last 4 weeks, not in the 4 weeks before, but active earlier), or gone "
                "quiet (active in the 4 weeks before, not in the last 4 weeks). How many accounts are in each group?"
            ),
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "metric_describe_before_adapted_sql": {},
                "query_terms_used": {"terms": _ACTIVE_ACCOUNT_TERMS},
                "semantic_layer_answer": {
                    "expected_behavior": _sql_from_typed_behavior(
                        "the count of accounts in each of the four groups, with the group definitions applied "
                        "exactly as the user stated them and each account in exactly one group"
                    )
                },
            },
            setup=seed_account_engagement_metric,
        ),
        SandboxedEvalCase(
            name="sql_from_typed_distribution",
            prompt=(
                "Among accounts that were active in the last 4 weeks by our definition, what is the median and the "
                "maximum number of active users per account, split by plan?"
            ),
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "metric_describe_before_adapted_sql": {},
                "query_terms_used": {"terms": [*_ACTIVE_ACCOUNT_TERMS, "person", "plan"]},
                "semantic_layer_answer": {
                    "expected_behavior": _sql_from_typed_behavior(
                        "per plan, the median and the maximum of the distinct users per active account, counted "
                        "in the last 4 weeks"
                    )
                },
            },
            setup=seed_account_engagement_metric,
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
            MetricFound(),
            InsightShape(),
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
                "metric_found",
                "insight_shape",
                "semantic_layer_answer",
            ],
        ),
    )
