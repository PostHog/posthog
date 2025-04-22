from collections.abc import Callable

import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import AssistantHogQLQuery, HumanMessage


@pytest.fixture(scope="module")
def metric():
    return GEval(
        name="SQL Plan Correctness",
        criteria="You will be given expected and actual generated SQL query plans to answer a user's question. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan.",
        evaluation_steps=[
            "Check if the plan includes the correct tables and fields needed to answer the question.",
            "Verify that the proposed way filtering matches the requirements in the user's question.",
            "Ensure that the right aggregations are mentioned (COUNT, SUM, AVG, etc.) to answer the question.",
            "Be flexible in your evaluation, as there are many ways to write a correct SQL query that answers the same question.",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )


@pytest.fixture
def call_node(team, runnable_config) -> Callable[[str], AssistantHogQLQuery]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.SQL_PLANNER)
        .add_sql_planner(AssistantNodeName.END, AssistantNodeName.END)
        .compile()
    )

    def callable(query: str):
        raw_state = graph.invoke(
            AssistantState(
                messages=[HumanMessage(content=query)],
                root_tool_insight_plan=query,
                root_tool_call_id="eval_test",
                root_tool_insight_type="sql",
            ),
            runnable_config,
        )
        state = AssistantState.model_validate(raw_state)
        return state.plan or "NO PLAN WAS GENERATED"

    return callable


def test_basic_count(metric, call_node):
    query = "What's our $pageview count over time"
    test_case = LLMTestCase(
        input=query,
        expected_output="""
Logic:
- Count the occurrences of the `$pageview` event.
- Group the counts by a time dimension, such as day, week, or month, depending on the granularity required.

Sources:
- `$pageview` event
    - Use the event to count occurrences and group by timestamp to analyze the count over time.""".strip(),
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])


def test_url_filtering_with_date_in_range(metric, call_node):
    query = "How many file downloads did we have in the last 5 days, "
    test_case = LLMTestCase(
        input=query,
        expected_output="""
Logic:
- Count the number of occurrences of the 'downloaded_file' event within the last 5 days.

Sources:
- Event: downloaded_file
    - Use this event to count the number of file downloads. Filter the event data to include only those that occurred in the last 5 days.""".strip(),
        actual_output=call_node(query),
    )
    assert_test(test_case, [metric])
