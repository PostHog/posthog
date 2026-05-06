"""Product analytics funnel eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_funnel.py`` — the CI version asserts
on the exact ``AssistantFunnelsQuery`` Max produces, this version exercises
the same intents end-to-end through the sandboxed agent + PostHog MCP tools
and judges the funnel query the agent ran via the ``query-funnel`` MCP tool.

To run:
    pytest ee/hogai/eval/sandboxed/product_analytics/eval_funnel.py
"""

from __future__ import annotations

from datetime import datetime

import pytest

from posthog.schema import (
    AssistantFunnelsEventsNode,
    AssistantFunnelsExclusionEventsNode,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
)

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.product_analytics.scorers import (
    INSIGHT_WRITE_TOOLS,
    FunnelSchemaAlignment,
    FunnelTimeRangeRelevancy,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, LastToolCallNot, NoToolCall, RequiredToolCall


def _funnel_case(
    *,
    name: str,
    prompt: str,
    query: AssistantFunnelsQuery,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "funnel_query": query.model_dump(exclude_none=True),
        },
    )


@pytest.mark.django_db
async def eval_funnel(sandboxed_demo_data, pytestconfig, posthog_client):
    this_year = datetime.now().year

    cases = [
        _funnel_case(
            name="funnel_pageview_to_signup",
            prompt="Conversion from page view to sign up",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelAggregateByHogQL="properties.$session_id",
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_question",
            prompt="what was the conversion from a page view to sign up?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_upload_download_chrome_safari_30d",
            prompt="What was the conversion from uploading a file to downloading it from Chrome and Safari in the last 30d?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                ),
                series=[
                    AssistantFunnelsEventsNode(
                        event="uploaded_file",
                        math=None,
                        properties=[
                            {
                                "key": "$browser",
                                "value": ["Chrome", "Safari"],
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                    ),
                    AssistantFunnelsEventsNode(
                        event="downloaded_file",
                        math=None,
                        properties=[
                            {
                                "key": "$browser",
                                "value": ["Chrome", "Safari"],
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                    ),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_upload_download_excluding_invites",
            prompt="What was the conversion from uploading a file to downloading it in the last 30d excluding users that invited a team member?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    exclusions=[
                        AssistantFunnelsExclusionEventsNode(
                            event="invited_team_member",
                            funnelFromStep=0,
                            funnelToStep=1,
                        )
                    ],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="uploaded_file", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="downloaded_file", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_upload_download_breakdown_browser",
            prompt="Show a conversion from uploading a file to downloading it segmented by a browser",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter={"breakdown": "$browser", "breakdown_type": "event"},
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="uploaded_file", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="downloaded_file", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_signup_to_personal_pro_paid",
            prompt="What was the conversion from a sign up to a paying customer on the personal-pro plan?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                    AssistantFunnelsEventsNode(
                        event="paid_bill",
                        math=None,
                        properties=[{"key": "plan", "value": "personal/pro", "operator": "exact", "type": "event"}],
                    ),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_signup_generic",
            prompt="What's our sign-up funnel?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_before_2024",
            prompt="what was the conversion from a page view to sign up for event time before 2024-01-01?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "2023-12-01", "date_to": "2024-01-01"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_yesterday",
            prompt="conversion from a page view to a sign up for yesterday",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-1d", "date_to": "dStart"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_last_1_week",
            prompt="conversion from a page view to a sign up for the last 1 week",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-7d"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_last_1_month",
            prompt="conversion from a page view to a sign up for the last 1 month",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-1m"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_last_80_days",
            prompt="conversion from a page view to a sign up for the last 80 days",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-80d"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_last_6_months",
            prompt="conversion from a page view to a sign up for the last 6 months",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-6m"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_from_2020_to_2025",
            prompt="conversion from a page view to a sign up from 2020 to 2025",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "2020-01-01", "date_to": "2025-12-31"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_default_30d",
            prompt="conversion from a page view to a sign up",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d"},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_signup_users_named_john",
            prompt="what is the conversion rate from a page view to sign up for users with name John?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(
                        event="$pageview",
                        math=None,
                        properties=[{"key": "name", "value": "John", "operator": "exact", "type": "person"}],
                    ),
                    AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_pageview_this_january",
            prompt="what is the conversion rate from a page view to a next page view in this January?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={
                    "date_from": f"{this_year}-01-01",
                    "date_to": f"{this_year}-01-31",
                },
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_pageview_this_january_by_session",
            prompt="what is the conversion rate from a page view to a next page view in this January aggregated by session?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={
                    "date_from": f"{this_year}-01-01",
                    "date_to": f"{this_year}-01-31",
                },
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                    funnelAggregateByHogQL="properties.$session_id",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_pageview_this_january_by_user",
            prompt="what is the conversion rate from a page view to a next page view in this January aggregated by user?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=None,
                breakdownFilter=None,
                dateRange={
                    "date_from": f"{this_year}-01-01",
                    "date_to": f"{this_year}-01-31",
                },
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                ],
            ),
        ),
        _funnel_case(
            name="funnel_pageview_to_pageview_this_january_by_account",
            prompt="what is the conversion rate from a page view to a next page view in this January aggregated by unique accounts?",
            query=AssistantFunnelsQuery(
                aggregation_group_type_index=0,
                breakdownFilter=None,
                dateRange={
                    "date_from": f"{this_year}-01-01",
                    "date_to": f"{this_year}-01-31",
                },
                filterTestAccounts=True,
                funnelsFilter=AssistantFunnelsFilter(
                    binCount=None,
                    exclusions=[],
                    funnelOrderType="ordered",
                    funnelStepReference="total",
                    funnelVizType="steps",
                    funnelWindowInterval=14,
                    funnelWindowIntervalUnit="day",
                ),
                series=[
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                    AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                ],
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-funnels",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            LastToolCallNot(forbidden="execute-sql", name="last_call_not_execute_sql"),
            RequiredToolCall(required={"read-data-schema"}, name="verified_event_exists"),
            FunnelSchemaAlignment(),
            FunnelTimeRangeRelevancy(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
