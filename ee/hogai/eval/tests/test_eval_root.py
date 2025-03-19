from collections.abc import Callable

import pytest
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from deepeval import assert_test
from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage, AssistantMessage
from deepeval.test_case import LLMTestCase, ToolCall
from deepeval.metrics import ToolCorrectnessMetric


@pytest.fixture
def call_node(team, runnable_config: RunnableConfig) -> Callable[[str], str]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "docs": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        .compile()
    )

    def callable(message: str) -> AssistantMessage:
        raw_state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=message)]),
            runnable_config,
        )
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


def test_create_insight_message_calls_sql_tool(call_node):
    message = "Create an SQL insight to calculate active users recently"
    actual_message = call_node(message)
    test_case = LLMTestCase(
        input=message,
        actual_output=actual_message.content,
        tools_called=[ToolCall(name=tool.name, input_parameters=tool.args) for tool in actual_message.tool_calls],
        expected_tools=[ToolCall(name="create_and_query_insight", input_parameters={"query_kind": "sql"})],
    )
    assert_test(test_case, [ToolCorrectnessMetric(strict_mode=True)])


def test_write_sql_message_calls_sql_tool(call_node):
    # This should ALSO refer to insight creation, as it's much more robust than a direct LLM message without research
    message = "Write SQL to calculate active users recently"
    actual_message = call_node(message)
    test_case = LLMTestCase(
        input=message,
        actual_output=actual_message.content,
        tools_called=[ToolCall(name=tool.name, input_parameters=tool.args) for tool in actual_message.tool_calls],
        expected_tools=[ToolCall(name="create_and_query_insight", input_parameters={"query_kind": "sql"})],
    )
    assert_test(test_case, [ToolCorrectnessMetric(strict_mode=True)])
