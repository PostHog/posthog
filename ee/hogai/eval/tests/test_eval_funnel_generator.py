from collections.abc import Callable
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
