from collections.abc import Callable
from typing import cast

import pytest
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage, RouterMessage


@pytest.fixture
def call_node(team, runnable_config) -> Callable[[str | list], str]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_start()
        .add_router(path_map={"trends": AssistantNodeName.END, "funnel": AssistantNodeName.END})
        .compile()
    )

    def callable(query: str | list) -> str:
        messages = [HumanMessage(content=query)] if isinstance(query, str) else query
        state = graph.invoke(
            AssistantState(messages=messages),
            runnable_config,
        )
        return cast(RouterMessage, AssistantState.model_validate(state).messages[-1]).content

    return callable


def test_outputs_basic_trends_insight(call_node):
    query = "Show the $pageview trend"
    res = call_node(query)
    assert res == "trends"


def test_outputs_basic_funnel_insight(call_node):
    query = "What is the conversion rate of users who uploaded a file to users who paid for a plan?"
    res = call_node(query)
    assert res == "funnel"


def test_converts_trends_to_funnel(call_node):
    conversation = [
        HumanMessage(content="Show trends of $pageview and $identify"),
        RouterMessage(content="trends"),
        HumanMessage(content="Convert this insight to a funnel"),
    ]
    res = call_node(conversation[:1])
    assert res == "trends"
    res = call_node(conversation)
    assert res == "funnel"


def test_converts_funnel_to_trends(call_node):
    conversation = [
        HumanMessage(content="What is the conversion from a page view to a sign up?"),
        RouterMessage(content="funnel"),
        HumanMessage(content="Convert this insight to a trends"),
    ]
    res = call_node(conversation[:1])
    assert res == "funnel"
    res = call_node(conversation)
    assert res == "trends"


def test_outputs_single_trends_insight(call_node):
    """
    Must display a trends insight because it's not possible to build a funnel with a single series.
    """
    query = "how many users upgraded their plan to personal pro?"
    res = call_node(query)
    assert res == "trends"


def test_classifies_funnel_with_single_series(call_node):
    query = "What's our sign-up funnel?"
    res = call_node(query)
    assert res == "funnel"
