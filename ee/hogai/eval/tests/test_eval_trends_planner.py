from collections.abc import Callable

import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.metrics import time_and_interval_correctness
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage


@pytest.fixture(scope="module")
def metric():
    return GEval(
        name="Trends Plan Correctness",
        criteria="You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a trends insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about trends insights.",
        evaluation_steps=[
            "A plan must define at least one event and a math type, but it is not required to define any filters, breakdowns, or formulas.",
            "Compare events, properties, math types, and property values of 'expected output' and 'actual output'. Do not penalize if the actual output does not include a timeframe.",
            "Check if the combination of events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.",
            # The criteria for aggregations must be more specific because there isn't a way to bypass them.
            "Check if the math types in 'actual output' match those in 'expected output'. Math types sometimes are interchangeable, so use your judgement. If the aggregation type is specified by a property, user, or group in 'expected output', the same property, user, or group must be used in 'actual output'.",
            "If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.",
            "If 'expected output' contains a formula, check if 'actual output' contains a similar formula, and heavily penalize if the formula is not present or different.",
            # We don't want to see in the output unnecessary property filters. The assistant tries to use them all the time.
            "Heavily penalize if the 'actual output' contains any excessive output not present in the 'expected output'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )


@pytest.fixture
def call_node(team, runnable_config: RunnableConfig) -> Callable[[str], str]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
        .add_trends_planner(AssistantNodeName.END, AssistantNodeName.END)
        .compile()
    )

    def callable(query: str) -> str:
        state = graph.invoke(
            AssistantState(
                messages=[HumanMessage(content=query)],
                root_tool_insight_plan=query,
                root_tool_call_id="eval_test",
                root_tool_insight_type="trends",
            ),
            runnable_config,
        )
        return AssistantState.model_validate(state).plan or ""

    return callable


def test_no_excessive_property_filters(metric, call_node):
    query = "Show the $pageview trend"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Events:
        - $pageview
            - math operation: total count
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_no_excessive_property_filters_for_a_defined_math_type(metric, call_node):
    query = "What is the MAU?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Events:
        - $pageview
            - math operation: unique users
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_basic_filtering(metric, call_node):
    query = "can you compare how many Chrome vs Safari users uploaded a file in the last 30d?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
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
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_formula_mode(metric, call_node):
    query = "i want to see a ratio of identify divided by page views"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Events:
        - $identify
            - math operation: total count
        - $pageview
            - math operation: total count

        Formula:
        `A/B`, where `A` is the total count of `$identify` and `B` is the total count of `$pageview`
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_math_type_by_a_property(metric, call_node):
    query = "what is the average session duration?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Events:
        - All Events
            - math operation: average by `$session_duration`
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_math_type_by_a_user(metric, call_node):
    query = "What is the median page view count for a user?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Events:
        - $pageview
            - math operation: median by users
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_needle_in_a_haystack(metric, call_node):
    query = "How frequently do people pay for a personal-pro plan?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
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
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_trends_for_unique_sessions(metric, call_node):
    query = "how many $pageviews with unique sessions did we have?"
    plan = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Events:
        - $pageview
            - math operation: unique sessions

        Time period: last month
        Time interval: day
        """,
        actual_output=plan,
        comments=plan,
    )
    assert_test(test_case, [metric])


@pytest.mark.parametrize(
    "time_period, time_interval",
    [
        ("for yesterday", "hour"),
        ("for the last 1 week", "day"),
        ("for the last 1 month", "week"),
        ("for the last 80 days", "week"),
        ("for the last 6 months", "month"),
        ("from 2020 to 2025", "month"),
        ("for 2023 by a week", "week"),
    ],
)
def test_trends_planner_handles_time_intervals(call_node, time_period, time_interval):
    query = f"$pageview trends {time_period}"
    plan = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_output=f"""
        Events:
        - $pageview
            - math operation: total count

        Time period: {time_period}
        Time interval: {time_interval}
        """,
        actual_output=plan,
    )
    assert_test(test_case, [time_and_interval_correctness("trends")])


def test_trends_planner_uses_default_time_period_and_interval(call_node):
    query = "$pageview trends"
    plan = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_output=f"""
        Events:
        - $pageview
            - math operation: total count

        Time period: last 30 days
        Time interval: day
        """,
        actual_output=plan,
    )
    assert_test(test_case, [time_and_interval_correctness("trends")])
