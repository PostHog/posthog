import json
from typing import TypedDict
from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.graph.funnels.toolkit import FUNNEL_SCHEMA
from ee.models.assistant import Conversation
from .conftest import MaxEval
import pytest
from braintrust import EvalCase
from autoevals.llm import LLMClassifier
from datetime import datetime

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import (
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantTrendsQuery,
    AssistantRetentionQuery,
    AssistantHogQLQuery,
    HumanMessage,
    VisualizationMessage,
    AssistantFunnelsFilter,
    AssistantFunnelsExclusionEventsNode,
)
from .scorers import TimeRangeRelevancy


class FunnelPlanCorrectness(LLMClassifier):
    """Evaluate if the generated plan correctly answers the user's question."""

    def __init__(self, **kwargs):
        super().__init__(
            name="plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a funnel insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about funnel insights.

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
1. A plan must define at least two series in the sequence, but it is not required to define any filters, exclusion steps, or a breakdown.
2. Compare events, properties, math types, and property values of 'expected plan' and 'output plan'. Do not penalize if the actual output does not include a timeframe unless specified in the 'expected plan'.
3. Check if the combination of events, properties, and property values in 'output plan' can answer the user's question according to the 'expected plan'.
4. Check if the math types in 'output plan' match those in 'expected plan.' If the aggregation type is specified by a property, user, or group in 'expected plan', the same property, user, or group must be used in 'generated plan'.
5. If 'expected plan' contains exclusion steps, check if 'output plan' contains those, and heavily penalize if the exclusion steps are not present or different.
6. If 'expected plan' contains a breakdown, check if 'output plan' contains a similar breakdown, and heavily penalize if the breakdown is not present or different. Plans may only have one breakdown.
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


class FunnelQueryAndPlanAlignment(LLMClassifier):
    """Evaluate if the generated funnel query aligns with the plan generated in the previous step."""

    def __init__(self, **kwargs):
        super().__init__(
            name="query_and_plan_alignment",
            prompt_template="""Evaluate if the generated funnel query aligns with the query plan.

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

Use knowledge of the FunnelQuery JSON schema, especially included descriptions:
<funnel_schema>
{{funnel_schema}}
</funnel_schema>

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
            funnel_schema=json.dumps(FUNNEL_SCHEMA),
            **kwargs,
        )


class CallNodeOutput(TypedDict):
    plan: str | None
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery | None


@pytest.fixture
def call_node(demo_org_team_user):
    # This graph structure will first get a plan, then generate the funnel.
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_PLANNER)
        .add_funnel_planner(next_node=AssistantNodeName.FUNNEL_GENERATOR)  # Planner output goes to generator
        .add_funnel_generator(AssistantNodeName.END)  # Generator output is the final output
        .compile()
    )

    def callable(query: str) -> CallNodeOutput:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
            root_tool_insight_plan=query,  # User query is the initial plan for the planner
            root_tool_call_id="eval_test",
            root_tool_insight_type="funnel",
        )

        # Invoke the graph. The state will be updated through planner and then generator.
        final_state_raw = graph.invoke(
            initial_state,
            {"configurable": {"thread_id": conversation.id}},
        )
        final_state = AssistantState.model_validate(final_state_raw)

        if not final_state.messages or not isinstance(final_state.messages[-1], VisualizationMessage):
            return {"plan": None, "query": None}

        return {"plan": final_state.messages[-1].plan, "query": final_state.messages[-1].answer}

    return callable


@pytest.mark.django_db
def eval_funnel(call_node):
    MaxEval(
        experiment_name="funnel",
        task=call_node,
        scores=[
            FunnelPlanCorrectness(),
            FunnelQueryAndPlanAlignment(),
            TimeRangeRelevancy(query_type="Funnels"),
        ],
        data=[
            EvalCase(
                input="Conversion from page view to sign up",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up
""",
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
                            layout="vertical",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(
                                event="$pageview",
                                math=None,
                            ),
                            AssistantFunnelsEventsNode(
                                event="signed_up",
                                math=None,
                            ),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what was the conversion from a page view to sign up?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up
""",
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
            ),
            EvalCase(
                input="What was the conversion from uploading a file to downloading it from Chrome and Safari in the last 30d?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. uploaded_file
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome, Safari
2. downloaded_file
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome, Safari
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            exclusions=[], funnelOrderType="ordered", funnelStepReference="total", funnelVizType="steps"
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
            ),
            EvalCase(
                input="What was the conversion from uploading a file to downloading it in the last 30d excluding users that invited a team member?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. uploaded_file
2. downloaded_file

Exclusions:
- invited_team_member
    - start index: 0
    - end index: 1
""",
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
            ),
            EvalCase(
                input="Show a conversion from uploading a file to downloading it segmented by a browser",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. uploaded_file
2. downloaded_file

Breakdown by:
- entity: event
- property name: $browser
""",
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
            ),
            EvalCase(
                input="What was the conversion from a sign up to a paying customer on the personal-pro plan?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. signed_up
2. paid_bill
    - property filter 1:
        - entity: event
        - property name: plan
        - property type: String
        - operator: equals
        - property value: personal/pro
""",
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
                                properties=[
                                    {"key": "plan", "value": "personal/pro", "operator": "exact", "type": "event"}
                                ],
                            ),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="What's our sign-up funnel?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up
""",
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
            ),
            EvalCase(
                input="what was the conversion from a page view to sign up for event time before 2024-01-01?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up

Time period: before 2024-01-01
Granularity: day
""",
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
                            funnelWindowInterval=14,  # Default, plan doesn't specify interval length
                            funnelWindowIntervalUnit="day",  # From plan
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up for yesterday",
                expected=CallNodeOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for yesterday",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-1d", "date_to": "dStart"},  # "yesterday"
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
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 1 week",
                expected=CallNodeOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 1 week",
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
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 1 month",
                expected=CallNodeOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 1 month",
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
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 80 days",
                expected=CallNodeOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 80 days",
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
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 6 months",
                expected=CallNodeOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 6 months",
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
            ),
            EvalCase(
                input="conversion from a page view to a sign up from 2020 to 2025",
                expected=CallNodeOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: from 2020 to 2025",
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
            ),
            EvalCase(
                input="conversion from a page view to a sign up",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up

Time period: last 30 days
Time interval: day
""",
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
                            funnelWindowIntervalUnit="day",  # from "Time interval: day"
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what is the conversion rate from a page view to sign up for users with name John?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
- property filter 1
    - person
    - name
    - equals
    - John
2. signed_up
""",
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
            ),
            EvalCase(
                input="what is the conversion rate from a page view to a next page view in this January?",
                expected=CallNodeOutput(
                    plan="""
Sequence:
1. $pageview
2. $pageview

Time period: this January
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
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
            ),
        ],
    )
