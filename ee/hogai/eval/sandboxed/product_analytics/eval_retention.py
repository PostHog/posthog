"""Product analytics retention eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_retention.py`` — the CI version asserts
on the exact ``AssistantRetentionQuery`` Max produces, this version exercises
the same intents end-to-end through the sandboxed agent + PostHog MCP tools
and judges the retention query the agent ran via the ``query-retention`` MCP
tool.

To run:
    pytest ee/hogai/eval/sandboxed/product_analytics/eval_retention.py
"""

from __future__ import annotations

import pytest

from posthog.schema import AssistantRetentionEventsNode, AssistantRetentionFilter, AssistantRetentionQuery

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.product_analytics.scorers import RetentionSchemaAlignment, RetentionTimeRangeRelevancy
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall

# PostHog MCP tools that persist saved-insight state. The sandbox is disposable
# but these tools still hit real rows, so any successful call is a bug in the
# agent's behaviour for a "just run the query" prompt.
INSIGHT_WRITE_TOOLS = frozenset(
    {
        "insight-create",
        "insight-update",
        "insight-partial-update",
        "insight-destroy",
    }
)


def _retention_case(
    *,
    name: str,
    prompt: str,
    query: AssistantRetentionQuery,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "retention_query": query.model_dump(exclude_none=True),
        },
    )


@pytest.mark.django_db
async def eval_retention(sandboxed_demo_data, pytestconfig, posthog_client):
    cases = [
        _retention_case(
            name="retention_pageview_default",
            prompt="Show user retention",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-11w", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Week",
                    totalIntervals=11,
                    returningEntity=AssistantRetentionEventsNode(id="$pageview"),
                    targetEntity=AssistantRetentionEventsNode(id="$pageview"),
                ),
            ),
        ),
        _retention_case(
            name="retention_signup_to_dashboard_monthly",
            prompt="Show monthly retention for users who sign up and then come back to view a dashboard",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-11M", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Month",
                    totalIntervals=11,
                    returningEntity=AssistantRetentionEventsNode(id="signed_up"),
                    targetEntity=AssistantRetentionEventsNode(id="viewed_dashboard"),
                ),
            ),
        ),
        _retention_case(
            name="retention_signup_to_purchase_daily_chrome",
            prompt="daily retention for Chrome users who sign up and then make a purchase",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-14d", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Day",
                    totalIntervals=14,
                    returningEntity=AssistantRetentionEventsNode(
                        id="signed_up",
                        properties=[
                            {
                                "key": "$browser",
                                "value": "Chrome",
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                    ),
                    targetEntity=AssistantRetentionEventsNode(id="purchased"),
                ),
            ),
        ),
        _retention_case(
            name="retention_signup_to_purchase_weekly_3mo",
            prompt="weekly retention breakdown by browser for users who sign up and then make a purchase in the last 3 months",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-3m", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Week",
                    totalIntervals=12,
                    returningEntity=AssistantRetentionEventsNode(id="signed_up"),
                    targetEntity=AssistantRetentionEventsNode(id="purchased"),
                ),
            ),
        ),
        _retention_case(
            name="retention_pricing_to_upgrade",
            prompt="what's the retention for users who view the pricing page and then upgrade their plan?",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-11w", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Week",
                    totalIntervals=11,
                    returningEntity=AssistantRetentionEventsNode(id="viewed_pricing_page"),
                    targetEntity=AssistantRetentionEventsNode(id="upgraded_plan"),
                ),
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-retention",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            RetentionSchemaAlignment(),
            RetentionTimeRangeRelevancy(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
