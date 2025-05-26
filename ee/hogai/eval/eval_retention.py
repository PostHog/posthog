from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.graph.retention.toolkit import RETENTION_SCHEMA
from ee.models.assistant import Conversation
from .conftest import MaxEval
import pytest
from braintrust import EvalCase

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import (
    AssistantRetentionQuery,
    AssistantRetentionFilter,
    AssistantRetentionEventsNode,
    HumanMessage,
    NodeKind,
    VisualizationMessage,
)
from .scorers import PlanCorrectness, QueryAndPlanAlignment, TimeRangeRelevancy, PlanAndQueryOutput


@pytest.fixture
def call_node(demo_org_team_user):
    # This graph structure will first get a plan, then generate the retention query.
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.RETENTION_PLANNER)
        .add_retention_planner(next_node=AssistantNodeName.RETENTION_GENERATOR)  # Planner output goes to generator
        .add_retention_generator(AssistantNodeName.END)  # Generator output is the final output
        .compile()
    )

    def callable(query: str) -> PlanAndQueryOutput:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
            root_tool_insight_plan=query,  # User query is the initial plan for the planner
            root_tool_call_id="eval_test_retention",
            root_tool_insight_type="retention",
        )

        # Invoke the graph. The state will be updated through planner and then generator.
        final_state_raw = graph.invoke(
            initial_state,
            {"configurable": {"thread_id": conversation.id}},
        )
        final_state = AssistantState.model_validate(final_state_raw)

        if not final_state.messages or not isinstance(final_state.messages[-1], VisualizationMessage):
            return {"plan": None, "query": None}

        # Ensure the answer is of the expected type for Retention eval
        answer = final_state.messages[-1].answer
        if not isinstance(answer, AssistantRetentionQuery):
            # This case should ideally not happen if the graph is configured correctly for Retention
            return {"plan": final_state.messages[-1].plan, "query": None}

        return {"plan": final_state.messages[-1].plan, "query": answer}

    return callable


@pytest.mark.django_db
def eval_retention(call_node):
    MaxEval(
        experiment_name="retention",
        task=call_node,
        scores=[
            PlanCorrectness(
                query_kind=NodeKind.RETENTION_QUERY,
                evaluation_criteria="""
1. A plan must define at least a returning event, and a target event, but it is not required to define any filters or breakdowns.
2. Compare returning events, target events, properties, and property values of 'expected plan' and 'output plan'. Do not penalize if the actual output does not include a timeframe unless specified in the 'expected plan'.
3. Check if the combination of events, properties, and property values in 'output plan' can answer the user's question according to the 'expected plan'.
4. If 'expected plan' contains a breakdown, check if 'output plan' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.
5. If 'expected plan' contains specific period settings (e.g., daily, weekly, monthly), check if 'output plan' contains the same period settings, and penalize if different.
6. Heavily penalize if the 'output plan' contains any excessive output not present in the 'expected plan'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.
""".strip(),
            ),
            QueryAndPlanAlignment(
                query_kind=NodeKind.RETENTION_QUERY,
                json_schema=RETENTION_SCHEMA,
                evaluation_criteria="""
1. Returning event alignment: Verify that the returning event in `retentionFilter.returningEntity.name` exactly matches the returning event specified in the plan.
2. Target event alignment: Verify that the target event in `retentionFilter.targetEntity.name` exactly matches the target event specified in the plan.
3. Period configuration: Ensure the retention period in `retentionFilter.period` matches what's specified in the plan:
   - "Day" for daily retention
   - "Week" for weekly retention
   - "Month" for monthly retention
   - Default to "Week" when not specified in the plan
4. Total intervals: Verify that `retentionFilter.totalIntervals` is set appropriately based on the period:
   - For daily: typically 14 intervals (14 days)
   - For weekly: typically 11 intervals (11 weeks)
   - For monthly: typically 11 intervals (11 months)
   - Should align with date range when specified in the plan
5. Property filters on returning entity: Check that property filters from the plan are correctly implemented on the returning event:
   - Property names, values, and operators must match exactly
   - Filter types (event, person, group) must be correct
   - Properties should be applied to `returningEntity.properties` when specified for the returning event
6. Property filters on target entity: Check that property filters from the plan are correctly implemented on the target event:
   - Property names, values, and operators must match exactly
   - Filter types (event, person, group) must be correct
   - Properties should be applied to `targetEntity.properties` when specified for the target event
7. Date range alignment: Verify that the date range matches the period and intervals:
   - Daily retention: date_from should be "-{totalIntervals}d"
   - Weekly retention: date_from should be "-{totalIntervals}w"
   - Monthly retention: date_from should be "-{totalIntervals}M"
   - Custom time periods from plan should be respected
8. Breakdown limitations: Note that retention queries currently don't support breakdown filters in the schema, so breakdown mentions in the plan cannot be fully implemented (this should not be heavily penalized as it's a schema limitation).
9. Missing implementation: Heavily penalize when key plan elements are missing (e.g., wrong events, incorrect period, missing property filters on correct entities).
10. Unnecessary fields: Penalize inclusion of fields not mentioned in the plan or that don't align with the retention intent.
""".strip(),
            ),
            TimeRangeRelevancy(query_kind=NodeKind.RETENTION_QUERY),
        ],
        data=[
            EvalCase(
                input="Show user retention",
                expected=PlanAndQueryOutput(
                    plan="""
Returning event: $pageview
Target event: $pageview
Period: Week
""",
                    query=AssistantRetentionQuery(
                        dateRange={"date_from": "-11w", "date_to": None},
                        filterTestAccounts=True,
                        retentionFilter=AssistantRetentionFilter(
                            period="Week",
                            totalIntervals=11,
                            returningEntity=AssistantRetentionEventsNode(name="$pageview"),
                            targetEntity=AssistantRetentionEventsNode(name="$pageview"),
                        ),
                    ),
                ),
            ),
            EvalCase(
                input="Show monthly retention for users who sign up and then come back to view a dashboard",
                expected=PlanAndQueryOutput(
                    plan="""
Returning event: signed_up
Target event: viewed_dashboard
Period: Month
""",
                    query=AssistantRetentionQuery(
                        dateRange={"date_from": "-11M", "date_to": None},
                        filterTestAccounts=True,
                        retentionFilter=AssistantRetentionFilter(
                            period="Month",
                            totalIntervals=11,
                            returningEntity=AssistantRetentionEventsNode(name="signed_up"),
                            targetEntity=AssistantRetentionEventsNode(name="viewed_dashboard"),
                        ),
                    ),
                ),
            ),
            EvalCase(
                input="daily retention for Chrome users who sign up and then make a purchase",
                expected=PlanAndQueryOutput(
                    plan="""
Returning event: signed_up
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome
Target event: purchased
Period: Day
""",
                    query=AssistantRetentionQuery(
                        dateRange={"date_from": "-14d", "date_to": None},
                        filterTestAccounts=True,
                        retentionFilter=AssistantRetentionFilter(
                            period="Day",
                            totalIntervals=14,
                            returningEntity=AssistantRetentionEventsNode(
                                name="signed_up",
                                properties=[
                                    {
                                        "key": "$browser",
                                        "value": "Chrome",
                                        "operator": "exact",
                                        "type": "event",
                                    },
                                ],
                            ),
                            targetEntity=AssistantRetentionEventsNode(name="purchased"),
                        ),
                    ),
                ),
            ),
            EvalCase(
                input="weekly retention breakdown by browser for users who sign up and then make a purchase in the last 3 months",
                # Tricky one, as AssistantRetentionQuery doesn't support `breakdownFilter` as of 2025-05-22!
                expected=PlanAndQueryOutput(
                    plan="""
Returning event: signed_up
Target event: purchased
Period: Week
Breakdown by:
    - entity: event
    - property name: $browser
Time period: last 3 months
""",
                    query=AssistantRetentionQuery(
                        dateRange={"date_from": "-3m", "date_to": None},
                        filterTestAccounts=True,
                        retentionFilter=AssistantRetentionFilter(
                            period="Week",
                            totalIntervals=12,
                            returningEntity=AssistantRetentionEventsNode(name="signed_up"),
                            targetEntity=AssistantRetentionEventsNode(name="purchased"),
                        ),
                    ),
                ),
            ),
            EvalCase(
                input="what's the retention for users who view the pricing page and then upgrade their plan?",
                expected=PlanAndQueryOutput(
                    plan="""
Returning event: viewed_pricing_page
Target event: upgraded_plan
Period: Week
""",
                    query=AssistantRetentionQuery(
                        dateRange={"date_from": "-11w", "date_to": None},
                        filterTestAccounts=True,
                        retentionFilter=AssistantRetentionFilter(
                            period="Week",
                            totalIntervals=11,
                            returningEntity=AssistantRetentionEventsNode(name="viewed_pricing_page"),
                            targetEntity=AssistantRetentionEventsNode(name="upgraded_plan"),
                        ),
                    ),
                ),
            ),
        ],
    )
