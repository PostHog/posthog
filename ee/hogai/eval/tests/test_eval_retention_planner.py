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
        name="Retention Plan Correctness",
        criteria="You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a retention insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about retention insights.",
        evaluation_steps=[
            "A plan must define both a target event (cohort-defining event) and a returning event (retention-measuring event), but it is not required to define any filters. It can't have breakdowns.",
            "Compare target event, returning event, properties, and property values of 'expected output' and 'actual output'. Do not penalize if the actual output does not include a timeframe.",
            "Check if the combination of target events, returning events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.",
            "If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.",
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
        .add_edge(AssistantNodeName.START, AssistantNodeName.RETENTION_PLANNER)
        .add_retention_planner(AssistantNodeName.END, AssistantNodeName.END)
        .compile()
    )

    def callable(query: str) -> str:
        raw_state = graph.invoke(
            AssistantState(
                messages=[HumanMessage(content=query)],
                root_tool_insight_plan=query,
                root_tool_call_id="eval_test",
                root_tool_insight_type="retention",
            ),
            runnable_config,
        )
        state = AssistantState.model_validate(raw_state)
        return state.plan or "NO PLAN WAS GENERATED"

    return callable


def test_basic_retention(metric, call_node):
    query = "What's the file upload retention of new users?"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Target event:
        - signed_up

        Returning event:
        - uploaded_file
        """,
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_basic_filtering(metric, call_node):
    query = "Show retention of Chrome users uploading files"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
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
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_needle_in_a_haystack(metric, call_node):
    query = "Show retention for users who have paid a bill and are on the personal/pro plan"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
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
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_retention_planner_sets_time_period_and_granularity(metric, call_node):
    query = "Show retention for users who have paid a bill from 2025-02-15 to 2025-02-21"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
        Target event:
        - paid_bill

        Returning event:
        - downloaded_file

        Time period: from 2025-02-15 to 2025-02-21
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
def test_retention_planner_handles_time_intervals(call_node, time_period):
    query = f"show retention of uploading files {time_period}"
    plan = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_output=f"""
        Target event:
        - uploaded_file

        Returning event:
        - uploaded_file

        Time period: {time_period}
        """,
        actual_output=plan,
    )
    assert_test(test_case, [time_and_interval_correctness("funnel")])


def test_trends_planner_uses_default_time_period_and_interval(call_node):
    query = "show retention of uploading files"
    plan = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_output=f"""
        Target event:
        - uploaded_file

        Returning event:
        - uploaded_file

        Time period: last 30 days
        Time interval: day
        """,
        actual_output=plan,
    )
    assert_test(test_case, [time_and_interval_correctness("funnel")])
