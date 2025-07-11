from datetime import datetime

import pytest
from braintrust import EvalCase

from ee.hogai.graph.trends.toolkit import TRENDS_SCHEMA
from posthog.schema import (
    AssistantEventMultipleBreakdownFilterType,
    AssistantGenericMultipleBreakdownFilter,
    AssistantTrendsBreakdownFilter,
    AssistantTrendsEventsNode,
    AssistantTrendsFilter,
    AssistantTrendsQuery,
    NodeKind,
)

from .conftest import MaxEval
from .scorers import PlanAndQueryOutput, PlanCorrectness, QueryAndPlanAlignment, QueryKindSelection, TimeRangeRelevancy


@pytest.mark.django_db
async def eval_trends(call_root_for_insight_generation):
    await MaxEval(
        experiment_name="trends",
        task=call_root_for_insight_generation,
        scores=[
            QueryKindSelection(expected=NodeKind.TRENDS_QUERY),
            PlanCorrectness(
                query_kind=NodeKind.TRENDS_QUERY,
                evaluation_criteria="""
1. A plan must define at least one event and a math type, but it is not required to define any filters, breakdowns, or formulas.
2. Compare events, properties, math types, and property values of 'expected plan' and 'output plan'. Do not penalize if the actual output does not include a timeframe.
3. Check if the combination of events, properties, and property values in 'output plan' can answer the user's question according to the 'expected plan'.
4. Check if the math types in 'output plan' match those in 'expected plan.' If the aggregation type is specified by a property, user, or group in 'expected plan', the same property, user, or group must be used in 'generated plan'.
5. If 'expected plan' contains a breakdown, check if 'output plan' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.
6. If 'expected plan' contains a formula, check if 'output plan' contains a similar formula, and heavily penalize if the formula is not present or different.
7. Heavily penalize if the 'output plan' contains any excessive output not present in the 'expected plan'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.
8. If the user's goal is to compare specific breakdown values, it's fine for the generated plan to split each breakdown value into a separate series, even if the expected plan achieves the same thing with a breakdown.
""",
            ),
            QueryAndPlanAlignment(
                query_kind=NodeKind.TRENDS_QUERY,
                json_schema=TRENDS_SCHEMA,
                evaluation_criteria="""
1. Events alignment: Verify that all events mentioned in the plan are correctly represented in the query's `series` array. For "All events", the `event` field should be `null`.
2. Series math: Ensure the math operation for each event in the query matches what's specified in the plan, for example:
   - "total count" → `math: "total"`
   - "unique users" → `math: "dau"` (legacy naming)
   - "unique sessions" → `math: "unique_session"`
   - "average/median/p95/etc. of [property]" → `math: "avg"/`"median"`/`"p95"`/etc. with correct `math_property`
   - Verify `math_property` is set only when required by the math operation
3. Property filters: Check that event properties and filters from the plan are correctly implemented:
   - Property names, values, and operators must match exactly
   - Multiple property values should be represented as arrays in the `value` field
   - Filter types (event, person, group) must be correct
4. Breakdowns: Verify breakdown implementation matches the plan:
   - Breakdown property names must match exactly
   - Breakdown types (event, person, group) must be correct
   - Multiple breakdowns should be represented in the `breakdowns` array
5. Formulas: For formula-based queries:
   - Check that the number of series matches the formula requirements
   - Verify that series are ordered correctly to match formula variables (A, B, C, etc.)
   - Formula logic should align with plan description
6. Display type: Verify appropriate display type selection:
   - Single value metrics (like MAU) can use `"BoldNumber"`, but often it's still better to use `"ActionsLineGraph"` for trend analysis
   - Trend analyses should use `"ActionsLineGraph"`
   - Display type should match the nature of the query described in the plan
9. Unnecessary fields: Penalize inclusion of fields not mentioned in the plan or that don't align with the query intent.
10. Missing implementation: Heavily penalize when key plan elements are completely missing from the generated query (e.g., missing breakdowns, wrong math operations, incorrect event selection).
""",
            ),
            TimeRangeRelevancy(query_kind=NodeKind.TRENDS_QUERY),
        ],
        data=[
            EvalCase(
                input="Show the $pageview trend",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- $pageview
    - math operation: total count
""",
                    query=AssistantTrendsQuery(
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph",
                            showLegend=True,
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="$pageview",
                                math="total",
                                properties=None,
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="What is our MAU?",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- All events
    - math operation: unique users

Time period: last 30 days
No interval
""",
                    query=AssistantTrendsQuery(
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        trendsFilter=AssistantTrendsFilter(
                            display="BoldNumber",
                            showLegend=True,
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event=None,
                                math="dau",  # "dau" name is a legacy misnomer, it actually just means "unique users"
                                properties=None,
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="can you compare how many Chrome vs Safari users uploaded a file in the last 30d?",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- uploaded_file
    - math operation: unique users
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome
- uploaded_file
    - math operation: unique users
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Safari
""",
                    query=AssistantTrendsQuery(
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph",
                            showLegend=True,
                        ),
                        breakdownFilter=AssistantTrendsBreakdownFilter(
                            breakdowns=[
                                AssistantGenericMultipleBreakdownFilter(
                                    property="$browser",
                                    type=AssistantEventMultipleBreakdownFilterType.EVENT,
                                )
                            ]
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="uploaded_file",
                                math="total",
                                properties=[
                                    {
                                        "key": "$browser",
                                        "value": ["Chrome", "Safari"],
                                        "operator": "exact",
                                        "type": "event",
                                    },
                                ],
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="i want to see a ratio of identify divided by page views",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- $identify
    - math operation: total count
- $pageview
    - math operation: total count

Formula:
`A/B`, where `A` is the total count of `$identify` and `B` is the total count of `$pageview`
""",
                    query=AssistantTrendsQuery(
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph", showLegend=True, formulas=["A/B"]
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="$identify",
                                math="total",
                                properties=None,
                            ),
                            AssistantTrendsEventsNode(
                                event="$pageview",
                                math="total",
                                properties=None,
                            ),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what is our average session duration?",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- All Events
    - math operation: average by `$session_duration`
""",
                    query=AssistantTrendsQuery(
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph",
                            showLegend=True,
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="$all_events",
                                math="avg",
                                math_property="$session_duration",
                                properties=None,
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="how many $pageviews with unique sessions did we have?",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- $pageview
    - math operation: unique sessions

Time period: last month
Time interval: day
""",
                    query=AssistantTrendsQuery(
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph",
                            showLegend=True,
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="$pageview",
                                math="unique_session",
                                properties=None,
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="How often do users view the website in this January?",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- $pageview
    - math operation: total count

Time period: this January
Time interval: day
""",
                    query=AssistantTrendsQuery(
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
                        },
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph",
                            showLegend=True,
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="$pageview",
                                math="total",
                                properties=None,
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="How many paid bill events have occurred with amount more than 20 usd in this January?",
                expected=PlanAndQueryOutput(
                    plan="""
Events:
- paid_bill
    - math operation: total count
    - property filter 1:
        - entity: event
        - property name: amount_usd
        - property type: Numeric
        - operator: greater than
        - property value: 20

Time period: this January
Time interval: day
""",
                    query=AssistantTrendsQuery(
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
                        },
                        filterTestAccounts=True,
                        interval="day",
                        trendsFilter=AssistantTrendsFilter(
                            display="ActionsLineGraph",
                            showLegend=True,
                        ),
                        series=[
                            AssistantTrendsEventsNode(
                                event="paid_bill",
                                math="total",
                                properties=[
                                    {
                                        "key": "amount_usd",
                                        "value": 20,
                                        "operator": "gt",
                                        "type": "event",
                                    },
                                ],
                            )
                        ],
                    ),
                ),
            ),
        ],
    )
