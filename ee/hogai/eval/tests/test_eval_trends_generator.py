from collections.abc import Callable
from datetime import datetime
from typing import cast

import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import AssistantTrendsQuery, HumanMessage, VisualizationMessage


@pytest.fixture
def call_node(team, runnable_config) -> Callable[[str, str], AssistantTrendsQuery]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
        .add_trends_generator(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str, plan: str) -> AssistantTrendsQuery:
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            runnable_config,
        )
        return cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1]).answer

    return callable


def test_node_replaces_equals_with_contains(call_node):
    query = "what is pageview trend for users with name John?"
    plan = """Events:
    - $pageview
        - math operation: total count
        - property filter 1
            - person
            - name
            - equals
            - John
    """
    actual_output = call_node(query, plan).model_dump_json(exclude_none=True)
    assert "exact" not in actual_output
    assert "icontains" in actual_output
    assert "John" not in actual_output
    assert "john" in actual_output


def test_node_leans_towards_line_graph(call_node):
    query = "How often do users download files?"
    # We ideally want to consider both total count of downloads per period, as well as how often a median user downloads
    plan = """Events:
    - downloaded_file
        - math operation: total count
    - downloaded_file
        - math operation: median count per user
    """
    actual_output = call_node(query, plan)
    assert actual_output.trendsFilter.display == "ActionsLineGraph"
    assert actual_output.series[0].kind == "EventsNode"
    assert actual_output.series[0].event == "downloaded_file"
    assert actual_output.series[0].math == "total"
    assert actual_output.series[1].kind == "EventsNode"
    assert actual_output.series[1].event == "downloaded_file"
    assert actual_output.series[1].math == "median_count_per_actor"


def test_current_date(call_node):
    query = "How often do users view the website in this January?"
    plan = """Events:
    - $pageview
        - math operation: total count
    """
    date_range = call_node(query, plan).dateRange
    assert date_range is not None
    year = str(datetime.now().year)
    assert (date_range.date_from and year in date_range.date_from) or (
        date_range.date_to and year in date_range.date_to
    )


@pytest.mark.parametrize(
    "query,expected_interval",
    [
        ("the last five years", "month"),
        ("the last 80 days", "week"),
        ("the last four weeks", "week"),
        ("the last 15 days", "day"),
        ("the last 12 hours", "hour"),
    ],
)
def test_granularity(call_node, query, expected_interval):
    plan = f"""Series:
    - event: $pageview
        - math operation: total count

    Time period: {query}
    """
    query = call_node(f"$pageview trends for {query}", plan)
    assert query.interval == expected_interval


def test_sets_default_30_days(call_node):
    date_metric = GEval(
        name="Date Correctness",
        criteria="You will be given a JSON object containing a date range. Check if the date range corresponds to the expected time period.",
        evaluation_steps=[
            "Check if the dates or duration is set to the expected time period.",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )

    query = "How many pageviews do we have?"
    plan = """Series:
    - event: $pageview
        - math operation: total count
    """

    schema = call_node(query, plan)
    test_case = LLMTestCase(
        input=query,
        expected_output="Last 30 days",
        actual_output=schema.dateRange.model_dump_json(exclude_none=True),
    )

    assert_test(test_case, [date_metric])
