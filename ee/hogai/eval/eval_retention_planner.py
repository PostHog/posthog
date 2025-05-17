import pytest
from autoevals.llm import LLMClassifier
from braintrust import EvalCase
from ee.models.assistant import Conversation

from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage

from .conftest import MaxEval


class RetentionPlanCorrectness(LLMClassifier):
    """Evaluate retention plan correctness against expected plan."""

    def __init__(self, **kwargs):
        super().__init__(
            name="retention_plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a retention insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about retention insights.

Evaluation criteria:
- A plan must define both a target event (cohort-defining event) and a returning event (retention-measuring event), but it is not required to define any filters. It can't have breakdowns.
- Compare target event, returning event, properties, and property values of 'expected output' and 'actual output'. Do not penalize if the actual output does not include a timeframe.
- Check if the combination of target events, returning events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.
- If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.
- Heavily penalize if the 'actual output' contains any excessive output not present in the 'expected output'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.

User question: {{input}}
Expected plan: {{expected}}
Actual plan: {{output}}

How would you rate the correctness of the actual plan? Choose one:
- perfect: The actual plan fully matches the expected plan in terms of target event, returning event, and filters.
- good: The actual plan uses the correct events but might have minor differences that don't affect the ability to answer the question.
- partial: The actual plan has some correct elements but is missing key components or includes unnecessary elements.
- incorrect: The actual plan would not answer the user's question correctly or is substantially different from the expected plan.""",
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class TimePeriodGranularityCorrectness(LLMClassifier):
    """Evaluate if time period and granularity are correctly interpreted."""

    def __init__(self, **kwargs):
        super().__init__(
            name="time_period_granularity_correctness",
            prompt_template="""Evaluate if the time period and granularity in the generated plan correctly match what was requested in the user's query.

User query: {{input}}
Generated plan: {{output}}

For time period analysis:
1. Check if the user specified a time period (like "last 7 days", "last month", "from January to March", etc.)
2. If specified, check if the generated plan correctly captures this time period
3. If not specified, a default time period (such as "last 30 days") is acceptable

For granularity analysis:
1. Check if the user specified a granularity (like "day", "week", "month")
2. If specified, check if the generated plan correctly uses this granularity
3. If not specified, the plan should use an appropriate granularity based on the time range:
   - For short periods (1-2 days): hourly
   - For medium periods (3-90 days): daily
   - For longer periods (3-24 months): weekly
   - For very long periods (>24 months): monthly

How would you rate the time period and granularity interpretation? Choose one:
- correct: Both time period and granularity are correct or appropriate defaults are used
- partial: Either time period or granularity is correct, but not both
- incorrect: Both time period and granularity are incorrect or inappropriate defaults are used""",
            choice_scores={
                "correct": 1.0,
                "partial": 0.5,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.RETENTION_PLANNER)
        .add_retention_planner(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str) -> str:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        raw_state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)]),
            {"configurable": {"thread_id": conversation.id}},
        )
        state = AssistantState.model_validate(raw_state)
        return state.plan or "NO PLAN WAS GENERATED"

    return callable


@pytest.mark.django_db
def eval_retention_planner(call_node):
    MaxEval(
        experiment_name="retention_planner",
        task=call_node,
        scores=[RetentionPlanCorrectness(), TimePeriodGranularityCorrectness()],
        data=[
            # Test basic retention
            EvalCase(
                input="What's the file upload retention of new users?",
                expected="""
        Target event:
        - signed_up

        Returning event:
        - uploaded_file
        """,
            ),
            # Test basic filtering
            EvalCase(
                input="Show retention of Chrome users uploading files",
                expected="""
        Target event:
        - uploaded_file

        Returning event:
        - uploaded_file

        Filters:
        - property filter 1:
            - entity: event
            - property name: $browser
            - property type: String
            - operator: equals
            - property value: Chrome
        """,
            ),
            # Test needle in a haystack
            EvalCase(
                input="Show retention for users who have paid a bill and are on the personal/pro plan",
                expected="""
        Target event:
        - paid_bill

        Returning event:
        - downloaded_file

        Filters:
            - property filter 1:
                - entity: account
                - property name: plan
                - property type: String
                - operator: equals
                - property value: personal/pro
        """,
            ),
            # Test retention planner sets time period and granularity
            EvalCase(
                input="Show retention for users who have paid a bill from 2025-02-15 to 2025-02-21",
                expected="""
        Target event:
        - paid_bill

        Returning event:
        - downloaded_file

        Time period: from 2025-02-15 to 2025-02-21
        Granularity: day
        """,
            ),
            # Test time periods
            EvalCase(
                input="show retention of uploading files for yesterday",
                expected="for yesterday",
            ),
            EvalCase(
                input="show retention of uploading files for the last 1 week",
                expected="for the last 1 week",
            ),
            EvalCase(
                input="show retention of uploading files for the last 1 month",
                expected="for the last 1 month",
            ),
            EvalCase(
                input="show retention of uploading files for the last 80 days",
                expected="for the last 80 days",
            ),
            EvalCase(
                input="show retention of uploading files for the last 6 months",
                expected="for the last 6 months",
            ),
            EvalCase(
                input="show retention of uploading files from 2020 to 2025",
                expected="from 2020 to 2025",
            ),
            # Test default time period and interval
            EvalCase(
                input="show retention of uploading files",
                expected="last 30 days",
            ),
        ],
    )
