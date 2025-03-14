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
        name="Funnel Plan Correctness",
        criteria="You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a funnel insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about funnel insights.",
        evaluation_steps=[
            "A plan must define at least two series in the sequence, but it is not required to define any filters, exclusion steps, or a breakdown.",
            "Compare events, properties, math types, and property values of 'expected output' and 'actual output'. Do not penalize if the actual output does not include a timeframe.",
            "Check if the combination of events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.",
            # The criteria for aggregations must be more specific because there isn't a way to bypass them.
            "Check if the math types in 'actual output' match those in 'expected output.' If the aggregation type is specified by a property, user, or group in 'expected output', the same property, user, or group must be used in 'actual output'.",
            "If 'expected output' contains exclusion steps, check if 'actual output' contains those, and heavily penalize if the exclusion steps are not present or different.",
            "If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different. Plans may only have one breakdown.",
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
        .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_PLANNER)
        .add_funnel_planner(AssistantNodeName.END, AssistantNodeName.END)
        .compile()
    )

    def callable(query: str) -> str:
        state = graph.invoke(
            AssistantState(
                messages=[HumanMessage(content=query)],
                root_tool_insight_plan=query,
                root_tool_call_id="eval_test",
                root_tool_insight_type="funnel",
            ),
            runnable_config,
        )
        return AssistantState.model_validate(state).plan or ""

    return callable


def test_basic_funnel(metric, call_node):
    query = "what was the conversion from a page view to sign up?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. $pageview
        2. signed_up
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_outputs_at_least_two_events(metric, call_node):
    """
    Ambigious query. The funnel must return at least two events.
    """
    query = "how many users paid a bill?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. any event
        2. upgrade_plan
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_no_excessive_property_filters(metric, call_node):
    query = "Show the user conversion from a sign up to a file download"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. signed_up
        2. downloaded_file
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_basic_filtering(metric, call_node):
    query = "What was the conversion from uploading a file to downloading it from Chrome and Safari in the last 30d?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
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
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_exclusion_steps(metric, call_node):
    query = "What was the conversion from uploading a file to downloading it in the last 30d excluding users that deleted a file?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. uploaded_file
        2. downloaded_file

        Exclusions:
        - deleted_file
            - start index: 0
            - end index: 1
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_breakdown(metric, call_node):
    query = "Show a conversion from uploading a file to downloading it segmented by a browser"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. uploaded_file
        2. downloaded_file

        Breakdown by:
        - entity: event
        - property name: $browser
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_needle_in_a_haystack(metric, call_node):
    query = "What was the conversion from a sign up to a paying customer on the personal-pro plan?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
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
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_planner_outputs_multiple_series_from_a_single_series_question(metric, call_node):
    query = "What's our sign-up funnel?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. $pageview
        2. signed_up
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_funnel_does_not_include_timeframe(metric, call_node):
    query = "what was the conversion from a page view to sign up for event time before 2024-01-01?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Sequence:
        1. $pageview
        2. signed_up

        Time period: before 2024-01-01
        Granularity: day
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


@pytest.mark.parametrize(
    "time_period",
    [
        "for yesterday",
        "for the last 1 week",
        "for the last 1 month",
        "for the last 80 days",
        "for the last 6 months",
        "from 2020 to 2025",
    ],
)
def test_funnel_planner_handles_time_intervals(call_node, time_period):
    query = f"conversion from a page view to a sign up for {time_period}"
    plan = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_output=f"""
        Sequence:
        1. $pageview
        2. signed_up

        Time period: {time_period}
        """,
        actual_output=plan,
        comments=plan,
    )
    assert_test(test_case, [time_and_interval_correctness("funnel")])


def test_trends_planner_uses_default_time_period_and_interval(call_node):
    query = "conversion from a page view to a sign up"
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
        comments=plan,
    )
    assert_test(test_case, [time_and_interval_correctness("funnel")])
