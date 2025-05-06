import pytest
from autoevals.llm import LLMClassifier
from braintrust import EvalCase
from ee.models.assistant import Conversation

from ee.hogai.graph.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage

from .conftest import MaxEval


class TrendsPlanCorrectness(LLMClassifier):
    """Evaluate trends plan correctness against expected plan."""

    def __init__(self, **kwargs):
        super().__init__(
            name="trends_plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a trends insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about trends insights.

Evaluation criteria:
- A plan must define at least one event and a math type, but it is not required to define any filters, breakdowns, or formulas.
- Compare events, properties, math types, and property values of 'expected output' and 'actual output'. Do not penalize if the actual output does not include a timeframe.
- Check if the combination of events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.
- Check if the math types in 'actual output' match those in 'expected output'. Math types sometimes are interchangeable, so use your judgement. If the aggregation type is specified by a property, user, or group in 'expected output', the same property, user, or group must be used in 'actual output'.
- If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.
- If 'expected output' contains a formula, check if 'actual output' contains a similar formula, and heavily penalize if the formula is not present or different.
- Heavily penalize if the 'actual output' contains any excessive output not present in the 'expected output'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.

User question: {{input}}
Expected plan: {{expected}}
Actual plan: {{output}}

How would you rate the correctness of the actual plan? Choose one:
- perfect: The actual plan fully matches the expected plan in terms of events, math types, filters, breakdowns, and formulas.
- good: The actual plan uses the correct events and math types but might have minor differences that don't affect the ability to answer the question.
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


class TimeAndIntervalCorrectness(LLMClassifier):
    """Evaluate if time period and interval are correctly interpreted."""

    def __init__(self, **kwargs):
        super().__init__(
            name="time_and_interval_correctness",
            prompt_template="""Evaluate if the time period and interval in the generated plan correctly match what was requested in the user's query.

User query: {{input}}
Expected time interval: {{expected}}
Generated plan: {{output}}

For time period analysis:
1. Check if the user specified a time period (like "last 7 days", "last month", "from January to March", etc.)
2. If specified, check if the generated plan correctly captures this time period
3. If not specified, a default time period is acceptable

For time interval analysis:
1. Check if the user specified a time interval (like "by day", "by week", "by month")
2. If specified, check if the generated plan correctly uses this interval
3. If not specified, the plan should use an appropriate interval based on the time range:
   - For short periods (1-2 days): hourly
   - For medium periods (3-90 days): daily
   - For longer periods (3-24 months): weekly
   - For very long periods (>24 months): monthly

How would you rate the time period and interval interpretation? Choose one:
- correct: Both time period and interval are correct or appropriate defaults are used
- partial: Either time period or interval is correct, but not both
- incorrect: Both time period and interval are incorrect or inappropriate defaults are used""",
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
        .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
        .add_trends_planner(AssistantNodeName.END)
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
def eval_trends_planner(call_node):
    MaxEval(
        experiment_name="trends_planner",
        task=call_node,
        scores=[TrendsPlanCorrectness(), TimeAndIntervalCorrectness()],
        data=[
            # Test no excessive property filters
            EvalCase(
                input="Show the $pageview trend",
                expected="""
        Events:
        - $pageview
            - math operation: total count
        """,
            ),
            # Test no excessive property filters for a defined math type
            EvalCase(
                input="What is the MAU?",
                expected="""
        Events:
        - $pageview
            - math operation: unique users
        """,
            ),
            # Test basic filtering
            EvalCase(
                input="can you compare how many Chrome vs Safari users uploaded a file in the last 30d?",
                expected="""
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
            ),
            # Test formula mode
            EvalCase(
                input="i want to see a ratio of identify divided by page views",
                expected="""
        Events:
        - $identify
            - math operation: total count
        - $pageview
            - math operation: total count

        Formula:
        `A/B`, where `A` is the total count of `$identify` and `B` is the total count of `$pageview`
        """,
            ),
            # Test math type by a property
            EvalCase(
                input="what is the average session duration?",
                expected="""
        Events:
        - All Events
            - math operation: average by `$session_duration`
        """,
            ),
            # Test math type by a user
            EvalCase(
                input="What is the median page view count for a user?",
                expected="""
        Events:
        - $pageview
            - math operation: median by users
        """,
            ),
            # Test needle in a haystack
            EvalCase(
                input="How frequently do people pay for a personal-pro plan?",
                expected="""
        Events:
        - paid_bill
            - math operation: total count
            - property filter 1:
                - entity: event
                - property name: plan
                - property type: String
                - operator: contains
                - property value: personal/pro
        """,
            ),
            # Test trends for unique sessions
            EvalCase(
                input="how many $pageviews with unique sessions did we have?",
                expected="""
        Events:
        - $pageview
            - math operation: unique sessions
        """,
            ),
            # Test time periods and intervals
            EvalCase(
                input="Show pageviews for yesterday",
                expected="hour",
            ),
            EvalCase(
                input="Show pageviews for the last 1 week",
                expected="day",
            ),
            EvalCase(
                input="Show pageviews for the last 1 month",
                expected="week",
            ),
            EvalCase(
                input="Show pageviews for the last 80 days",
                expected="week",
            ),
            EvalCase(
                input="Show pageviews for the last 6 months",
                expected="month",
            ),
            EvalCase(
                input="Show pageviews from 2020 to 2025",
                expected="month",
            ),
            EvalCase(
                input="Show pageviews for 2023 by a week",
                expected="week",
            ),
        ],
    )
