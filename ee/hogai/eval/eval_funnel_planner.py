import pytest
from autoevals.llm import LLMClassifier
from braintrust import EvalCase
from ee.models.assistant import Conversation

from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage

from .conftest import MaxEval


class FunnelPlanCorrectness(LLMClassifier):
    """Evaluate funnel plan correctness against expected plan."""

    def __init__(self, **kwargs):
        super().__init__(
            name="funnel_plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a funnel insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about funnel insights.

Evaluation criteria:
- A plan must define at least two series in the sequence, but it is not required to define any filters, exclusion steps, or a breakdown.
- Compare events, properties, math types, and property values of 'expected output' and 'actual output'. Do not penalize if the actual output does not include a timeframe.
- Check if the combination of events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.
- Check if the math types in 'actual output' match those in 'expected output.' If the aggregation type is specified by a property, user, or group in 'expected output', the same property, user, or group must be used in 'actual output'.
- If 'expected output' contains exclusion steps, check if 'actual output' contains those, and heavily penalize if the exclusion steps are not present or different.
- If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different. Plans may only have one breakdown.
- Heavily penalize if the 'actual output' contains any excessive output not present in the 'expected output'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.

User question: {{input}}
Expected plan: {{expected}}
Actual plan: {{output}}

How would you rate the correctness of the actual plan? Choose one:
- perfect: The actual plan fully matches the expected plan in terms of sequence, filters, exclusions, and breakdown.
- good: The actual plan uses the correct sequence but might have minor differences that don't affect the ability to answer the question.
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


class TimePeriodCorrectness(LLMClassifier):
    """Evaluate if time period is correctly interpreted."""

    def __init__(self, **kwargs):
        super().__init__(
            name="time_period_correctness",
            prompt_template="""Evaluate if the time period in the generated plan correctly matches what was requested in the user's query.

User query: {{input}}
Generated plan: {{output}}

For time period analysis:
1. Check if the user specified a time period (like "last 7 days", "last month", "from January to March", etc.)
2. If specified, check if the generated plan correctly captures this time period
3. If not specified, a default time period is acceptable

How would you rate the time period interpretation? Choose one:
- correct: The time period is correctly specified or an appropriate default is used
- incorrect: The time period is incorrectly specified or an inappropriate default is used""",
            choice_scores={
                "correct": 1.0,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_PLANNER)
        .add_funnel_planner(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str) -> str:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)]),
            {"configurable": {"thread_id": conversation.id}},
        )
        return AssistantState.model_validate(state).plan or ""

    return callable


@pytest.mark.django_db
def eval_funnel_planner(call_node):
    MaxEval(
        experiment_name="funnel_planner",
        task=call_node,
        scores=[FunnelPlanCorrectness(), TimePeriodCorrectness()],
        data=[
            # Test basic funnel
            EvalCase(
                input="what was the conversion from a page view to sign up?",
                expected="""
        Sequence:
        1. $pageview
        2. signed_up
        """,
            ),
            # Test outputs at least two events
            EvalCase(
                input="how many users paid a bill?",
                expected="""
        Sequence:
        1. any event
        2. upgrade_plan
        """,
            ),
            # Test no excessive property filters
            EvalCase(
                input="Show the user conversion from a sign up to a file download",
                expected="""
        Sequence:
        1. signed_up
        2. downloaded_file
        """,
            ),
            # Test basic filtering
            EvalCase(
                input="What was the conversion from uploading a file to downloading it from Chrome and Safari in the last 30d?",
                expected="""
        Sequence:
        1. uploaded_file
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
        2. downloaded_file
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
        """,
            ),
            # Test exclusion steps
            EvalCase(
                input="What was the conversion from uploading a file to downloading it in the last 30d excluding users that deleted a file?",
                expected="""
        Sequence:
        1. uploaded_file
        2. downloaded_file

        Exclusions:
        - deleted_file
            - start index: 0
            - end index: 1
        """,
            ),
            # Test breakdown
            EvalCase(
                input="Show a conversion from uploading a file to downloading it segmented by a browser",
                expected="""
        Sequence:
        1. uploaded_file
        2. downloaded_file

        Breakdown by:
        - entity: event
        - property name: $browser
        """,
            ),
            # Test needle in a haystack
            EvalCase(
                input="What was the conversion from a sign up to a paying customer on the personal-pro plan?",
                expected="""
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
            ),
            # Test planner outputs multiple series from a single series question
            EvalCase(
                input="How many users have paid a bill?",
                expected="""
        Sequence:
        1. any event
        2. paid_bill
        """,
            ),
            # Test time period
            EvalCase(
                input="Show user conversion from signup to file download for yesterday",
                expected="yesterday",
            ),
            EvalCase(
                input="Show user conversion from signup to file download for the last 1 week",
                expected="last 1 week",
            ),
            EvalCase(
                input="Show user conversion from signup to file download for the last 1 month",
                expected="last 1 month",
            ),
            EvalCase(
                input="Show user conversion from signup to file download for the last 80 days",
                expected="last 80 days",
            ),
            EvalCase(
                input="Show user conversion from signup to file download for the last 6 months",
                expected="last 6 months",
            ),
            EvalCase(
                input="Show user conversion from signup to file download from 2020 to 2025",
                expected="from 2020 to 2025",
            ),
        ],
    )
