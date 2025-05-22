import json
from typing import TypedDict
from ee.hogai.graph import InsightsAssistantGraph
from ee.models.assistant import Conversation
from .conftest import MaxEval
import pytest
from braintrust import EvalCase, Score
from autoevals.llm import LLMClassifier
from braintrust_core.score import Scorer

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import (
    AssistantRetentionQuery,
    AssistantRetentionFilter,
    AssistantRetentionEventsNode,
    HumanMessage,
    VisualizationMessage,
)

# Define an empty schema as placeholder
RETENTION_SCHEMA = {
    "description": "Retention query schema for PostHog",
    "properties": {"retentionFilter": {"type": "object", "description": "Retention filter configuration"}},
}


class RetentionPlanCorrectness(LLMClassifier):
    """Evaluate if the generated plan correctly answers the user's question."""

    def __init__(self, **kwargs):
        super().__init__(
            name="plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a retention insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about retention insights.

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
1. A plan must define at least a returning event, and a target event, but it is not required to define any filters or breakdowns.
2. Compare returning events, target events, properties, and property values of 'expected plan' and 'output plan'. Do not penalize if the actual output does not include a timeframe unless specified in the 'expected plan'.
3. Check if the combination of events, properties, and property values in 'output plan' can answer the user's question according to the 'expected plan'.
4. If 'expected plan' contains a breakdown, check if 'output plan' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.
5. If 'expected plan' contains specific period settings (e.g., daily, weekly, monthly), check if 'output plan' contains the same period settings, and penalize if different.
6. Heavily penalize if the 'output plan' contains any excessive output not present in the 'expected plan'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.

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


class RetentionQueryAndPlanAlignment(LLMClassifier):
    """Evaluate if the generated retention query aligns with the plan generated in the previous step."""

    def __init__(self, **kwargs):
        super().__init__(
            name="query_and_plan_alignment",
            prompt_template="""Evaluate if the generated retention query aligns with the query plan.

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

Use knowledge of the RetentionQuery JSON schema, especially included descriptions:
<retention_schema>
{{retention_schema}}
</retention_schema>

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
            retention_schema=json.dumps(RETENTION_SCHEMA),
            **kwargs,
        )


class PeriodCorrectness(Scorer):
    """Evaluate if the period in the retention query is correct."""

    def _name(self):
        return "period_correctness"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        query = output["query"]
        query_description = kwargs.get("input", {})

        if not query or not hasattr(query, "retentionFilter") or not hasattr(query.retentionFilter, "period"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No retention query or period"})

        period = query.retentionFilter.period
        if not period:
            return Score(name=self._name(), score=0.0, metadata={"reason": "period is None"})

        # Check for specific period requirements in the query description
        if "daily" in query_description.lower() and period != "Day":
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"For 'daily' retention, expected period 'Day', got '{period}'"},
            )
        elif "weekly" in query_description.lower() and period != "Week":
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"For 'weekly' retention, expected period 'Week', got '{period}'"},
            )
        elif "monthly" in query_description.lower() and period != "Month":
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"For 'monthly' retention, expected period 'Month', got '{period}'"},
            )

        # Default score if no specific period-related checks from input_query trigger a failure.
        return Score(name=self._name(), score=1.0)


class DateCorrectness(Scorer):
    """Evaluate if the date range in the retention query is correct."""

    def _name(self):
        return "date_correctness"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        query = output["query"]
        query_description = kwargs.get("input", {})

        if not query or not hasattr(query, "dateRange"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No retention query or dateRange"})

        date_range = query.dateRange
        if not date_range:
            return Score(name=self._name(), score=0.0, metadata={"reason": "dateRange is None"})

        # Specific check for "last 3 months"
        if "last 3 months" in query_description.lower():
            if date_range.date_from != "-3m":
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={"reason": f"For 'last 3 months', expected date_from '-3m', got '{date_range.date_from}'"},
                )
            return Score(name=self._name(), score=1.0)

        # Default score if no specific date-related checks from input_query trigger a success or failure.
        return Score(name=self._name(), score=1.0)


class CallNodeOutput(TypedDict):
    plan: str | None
    query: AssistantRetentionQuery | None


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

    def callable(query: str) -> CallNodeOutput:
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

        return {"plan": final_state.messages[-1].plan, "query": final_state.messages[-1].answer}

    return callable


@pytest.mark.django_db
def eval_retention(call_node):
    MaxEval(
        experiment_name="retention",
        task=call_node,
        scores=[
            RetentionPlanCorrectness(),
            RetentionQueryAndPlanAlignment(),
            PeriodCorrectness(),
            DateCorrectness(),
        ],
        data=[
            EvalCase(
                input="Show user retention",
                expected=CallNodeOutput(
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
                expected=CallNodeOutput(
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
                expected=CallNodeOutput(
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
                expected=CallNodeOutput(
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
                expected=CallNodeOutput(
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
