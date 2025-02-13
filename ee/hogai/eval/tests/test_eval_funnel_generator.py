from collections.abc import Callable
from datetime import datetime
from typing import cast

import pytest
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import AssistantFunnelsQuery, HumanMessage, VisualizationMessage


@pytest.fixture
def call_node(team, runnable_config) -> Callable[[str, str], AssistantFunnelsQuery]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR)
        .add_funnel_generator(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str, plan: str) -> AssistantFunnelsQuery:
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            runnable_config,
        )
        return cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1]).answer

    return callable


def test_node_replaces_equals_with_contains(call_node):
    query = "what is the conversion rate from a page view to sign up for users with name John?"
    plan = """Sequence:
    1. $pageview
    - property filter 1
        - person
        - name
        - equals
        - John
    2. signed_up
    """
    actual_output = call_node(query, plan).model_dump_json(exclude_none=True)
    assert "exact" not in actual_output
    assert "icontains" in actual_output
    assert "John" not in actual_output
    assert "john" in actual_output


def test_current_date(call_node):
    query = "what is the conversion rate from a page view to a next page view in this January?"
    plan = """Sequence:
    1. $pageview
    2. $pageview
    """
    date_range = call_node(query, plan).dateRange
    assert date_range is not None
    year = str(datetime.now().year)
    assert (date_range.date_from and year in date_range.date_from) or (
        date_range.date_to and year in date_range.date_to
    )
