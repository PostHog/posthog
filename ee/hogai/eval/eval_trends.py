import json
from typing import TypedDict
from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.graph.trends.toolkit import TRENDS_SCHEMA
from ee.models.assistant import Conversation
from .conftest import MaxEval
import pytest
from braintrust import EvalCase
from autoevals.llm import LLMClassifier
from datetime import datetime

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import (
    AssistantTrendsQuery,
    AssistantTrendsEventsNode,
    AssistantTrendsFilter,
    AssistantTrendsBreakdownFilter,
    AssistantGenericMultipleBreakdownFilter,
    AssistantEventMultipleBreakdownFilterType,
    HumanMessage,
    VisualizationMessage,
)
from .scorers import TimeRangeRelevancy


class TrendsPlanCorrectness(LLMClassifier):
    """Evaluate if the generated plan correctly answers the user's question."""

    def __init__(self, **kwargs):
        super().__init__(
            name="plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a trends insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about trends insights.

User question:
<user_question>
{{input}}
</user_question>

Expected plan:
<expected_plan>
{{expected.plan}}
</expected_plan>

Actual generated plan:
<output_plan>
{{output.plan}}
</output_plan>

Evaluation criteria:
1. A plan must define at least one event and a math type, but it is not required to define any filters, breakdowns, or formulas.
2. Compare events, properties, math types, and property values of 'expected plan' and 'output plan'. Do not penalize if the actual output does not include a timeframe.
3. Check if the combination of events, properties, and property values in 'output plan' can answer the user's question according to the 'expected plan'.
4. Check if the math types in 'output plan' match those in 'expected plan.' If the aggregation type is specified by a property, user, or group in 'expected plan', the same property, user, or group must be used in 'generated plan'.
5. If 'expected plan' contains a breakdown, check if 'output plan' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.
6. If 'expected plan' contains a formula, check if 'output plan' contains a similar formula, and heavily penalize if the formula is not present or different.
7. Heavily penalize if the 'output plan' contains any excessive output not present in the 'expected plan'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.

How would you rate the correctness of the plan? Choose one:
- perfect: The plan fully matches the expected plan and addresses the user question.
- near_perfect: The plan mostly matches the expected plan with at most one immaterial detail missed from the user question.
- slightly_off: The plan mostly matches the expected plan with minor discrepancies.
- somewhat_misaligned: The plan has some correct elements but misses key aspects of the expected plan or question.
- strongly_misaligned: The plan does not match the expected plan or fails to address the user question.
- useless: The plan is incomprehensible.""",
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "useless": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class TrendsQueryAndPlanAlignment(LLMClassifier):
    """Evaluate if the generated trends query aligns with the plan generated in the previous step."""

    def __init__(self, **kwargs):
        super().__init__(
            name="query_and_plan_alignment",
            prompt_template="""Evaluate if the generated trends query aligns with the query plan.

<input_vs_output>

Original user question:
<user_question>
{{input}}
</user_question>

Generated query plan:
<plan>
{{output.plan}}
</plan>

Actual generated query that should be aligned with the plan:
<output_query>
{{output.query}}
</output_query>

</input_vs_output>

Use knowledge of the TrendsQuery JSON schema, especially included descriptions:
<trends_schema>
{{trends_schema}}
</trends_schema>

How would you rate the alignment of the generated query with the plan? Choose one:
- perfect: The generated query fully matches the plan.
- near_perfect: The generated query matches the plan with at most one immaterial detail missed from the user question.
- slightly_off: The generated query mostly matches the plan, with minor discrepancies that may slightly change the meaning of the query.
- somewhat_misaligned: The generated query has some correct elements, but misses key aspects of the plan.
- strongly_misaligned: The generated query does not match the plan and fails to address the user question.
- useless: The generated query is basically incomprehensible.
""",
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "useless": 0.0,
            },
            model="gpt-4.1",
            trends_schema=json.dumps(TRENDS_SCHEMA),
            **kwargs,
        )


class CallNodeOutput(TypedDict):
    plan: str | None
    query: AssistantTrendsQuery | None


@pytest.fixture
def call_node(demo_org_team_user):
    # This graph structure will first get a plan, then generate the trends query.
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
        .add_trends_planner(next_node=AssistantNodeName.TRENDS_GENERATOR)  # Planner output goes to generator
        .add_trends_generator(AssistantNodeName.END)  # Generator output is the final output
        .compile()
    )

    def callable(query: str) -> CallNodeOutput:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
            root_tool_insight_plan=query,  # User query is the initial plan for the planner
            root_tool_call_id="eval_test_trends",
            root_tool_insight_type="trends",
        )

        # Invoke the graph. The state will be updated through planner and then generator.
        final_state_raw = graph.invoke(
            initial_state,
            {"configurable": {"thread_id": conversation.id}},
        )
        final_state = AssistantState.model_validate(final_state_raw)

        if not final_state.messages or not isinstance(final_state.messages[-1], VisualizationMessage):
            return {"plan": None, "query": None}

        # Ensure the answer is of the expected type for Trends eval
        answer = final_state.messages[-1].answer
        if not isinstance(answer, AssistantTrendsQuery):
            # This case should ideally not happen if the graph is configured correctly for Trends
            return {"plan": final_state.messages[-1].plan, "query": None}

        return {"plan": final_state.messages[-1].plan, "query": answer}

    return callable


@pytest.mark.django_db
def eval_trends(call_node):
    MaxEval(
        experiment_name="trends",
        task=call_node,
        scores=[
            TrendsPlanCorrectness(),
            TrendsQueryAndPlanAlignment(),
            TimeRangeRelevancy(query_type="Trends"),
        ],
        data=[
            EvalCase(
                input="Show the $pageview trend",
                expected=CallNodeOutput(
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
                input="What is the MAU?",
                expected=CallNodeOutput(
                    plan="""
Events:
- $pageview
    - math operation: unique users
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
                                event="$pageview",
                                math="dau",  # "dau" name is a legacy misnomer, it actually just means "unique users"
                                properties=None,
                            )
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="can you compare how many Chrome vs Safari users uploaded a file in the last 30d?",
                expected=CallNodeOutput(
                    plan="""
Events:
- uploaded_file
    - math operation: total count
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome
    - property filter 2:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Safari

Breakdown by:
- breakdown 1:
    - entity: event
    - property name: $browser
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
                expected=CallNodeOutput(
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
                            display="ActionsLineGraph",
                            showLegend=True,
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
                input="what is the average session duration?",
                expected=CallNodeOutput(
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
                expected=CallNodeOutput(
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
                expected=CallNodeOutput(
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
        ],
    )
