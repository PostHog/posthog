import json
from collections.abc import Callable
from typing import Optional

import pytest
from deepeval import assert_test
from deepeval.metrics import GEval, ToolCorrectnessMetric
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage


@pytest.fixture
def retrieval_metrics():
    retrieval_correctness_metric = GEval(
        name="Correctness",
        criteria="Determine whether the actual output is factually correct based on the expected output.",
        evaluation_steps=[
            "Check whether the facts in 'actual output' contradicts any facts in 'expected output'",
            "You should also heavily penalize omission of detail",
            "Vague language, or contradicting OPINIONS, are OK",
            "The actual fact must only contain information about the user's company or product",
            "Context must not contain similar information to the actual fact",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.CONTEXT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )

    return [ToolCorrectnessMetric(), retrieval_correctness_metric]


@pytest.fixture
def replace_metrics():
    retrieval_correctness_metric = GEval(
        name="Correctness",
        criteria="Determine whether the actual output tuple is factually correct based on the expected output tuple. The first element is the original fact from the context to replace with, while the second element is the new fact to replace it with.",
        evaluation_steps=[
            "Check whether the facts in 'actual output' contradicts any facts in 'expected output'",
            "You should also heavily penalize omission of detail",
            "Vague language, or contradicting OPINIONS, are OK",
            "The actual fact must only contain information about the user's company or product",
            "Context must contain the first element of the tuples",
            "For deletion, the second element should be an empty string in both the actual and expected output",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.CONTEXT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )

    return [ToolCorrectnessMetric(), retrieval_correctness_metric]


@pytest.fixture
def call_node(team, runnable_config: RunnableConfig) -> Callable[[str], Optional[AIMessage]]:
    graph: CompiledStateGraph = (
        AssistantGraph(team).add_memory_collector(AssistantNodeName.END, AssistantNodeName.END).compile()
    )

    def callable(query: str) -> Optional[AIMessage]:
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)]),
            runnable_config,
        )
        validated_state = AssistantState.model_validate(state)
        if not validated_state.memory_collection_messages:
            return None
        return validated_state.memory_collection_messages[-1]

    return callable


def test_saves_relevant_fact(call_node, retrieval_metrics, core_memory):
    query = "calculate ARR: use the paid_bill event and the amount property."
    actual_output = call_node(query)
    tool = actual_output.tool_calls[0]

    test_case = LLMTestCase(
        input=query,
        expected_output="The product uses the event paid_bill and the property amount to calculate Annual Recurring Revenue (ARR).",
        expected_tools=["core_memory_append"],
        context=[core_memory.formatted_text],
        actual_output=tool["args"]["memory_content"],
        tools_called=[tool["name"]],
    )
    assert_test(test_case, retrieval_metrics)


def test_saves_company_related_information(call_node, retrieval_metrics, core_memory):
    query = "Our secondary target audience is technical founders or highly-technical product managers."
    actual_output = call_node(query)
    tool = actual_output.tool_calls[0]

    test_case = LLMTestCase(
        input=query,
        expected_output="The company's secondary target audience is technical founders or highly-technical product managers.",
        expected_tools=["core_memory_append"],
        context=[core_memory.formatted_text],
        actual_output=tool["args"]["memory_content"],
        tools_called=[tool["name"]],
    )
    assert_test(test_case, retrieval_metrics)


def test_omits_irrelevant_personal_information(call_node):
    query = "My name is John Doherty."
    actual_output = call_node(query)
    assert actual_output is None


def test_omits_irrelevant_excessive_info_from_insights(call_node):
    query = "Build a pageview trend for users with name John."
    actual_output = call_node(query)
    assert actual_output is None


def test_fact_replacement(call_node, core_memory, replace_metrics):
    query = "Hedgebox doesn't sponsor the YouTube channel Marius Tech Tips anymore."
    actual_output = call_node(query)
    tool = actual_output.tool_calls[0]

    test_case = LLMTestCase(
        input=query,
        expected_output=json.dumps(
            [
                "Hedgebox sponsors the YouTube channel Marius Tech Tips.",
                "Hedgebox no longer sponsors the YouTube channel Marius Tech Tips.",
            ]
        ),
        expected_tools=["core_memory_replace"],
        context=[core_memory.formatted_text],
        actual_output=json.dumps([tool["args"]["original_fragment"], tool["args"]["new_fragment"]]),
        tools_called=[tool["name"]],
    )
    assert_test(test_case, replace_metrics)


def test_fact_removal(call_node, core_memory, replace_metrics):
    query = "Delete info that Hedgebox sponsored the YouTube channel Marius Tech Tips."
    actual_output = call_node(query)
    tool = actual_output.tool_calls[0]

    test_case = LLMTestCase(
        input=query,
        expected_output=json.dumps(["Hedgebox sponsors the YouTube channel Marius Tech Tips.", ""]),
        expected_tools=["core_memory_replace"],
        context=[core_memory.formatted_text],
        actual_output=json.dumps([tool["args"]["original_fragment"], tool["args"]["new_fragment"]]),
        tools_called=[tool["name"]],
    )
    assert_test(test_case, replace_metrics)


def test_parallel_calls(call_node):
    query = "Delete info that Hedgebox sponsored the YouTube channel Marius Tech Tips, and we don't have file sharing."
    actual_output = call_node(query)

    tool = actual_output.tool_calls
    test_case = LLMTestCase(
        input=query,
        expected_tools=["core_memory_replace", "core_memory_append"],
        actual_output=actual_output.content,
        tools_called=[tool[0]["name"], tool[1]["name"]],
    )
    assert_test(test_case, [ToolCorrectnessMetric()])


def test_memory_collector_does_not_answer_to_user(call_node):
    query = "What is a unicorn product?"
    actual_output = call_node(query)
    assert actual_output is None


def test_saves_explicitly_requested_information(call_node):
    query = "Remember that I like to view the pageview trend broken down by a country."
    actual_output = call_node(query)

    test_case = LLMTestCase(
        input=query,
        expected_tools=["core_memory_append"],
        actual_output=actual_output.content,
        tools_called=[tool["name"] for tool in actual_output.tool_calls],
    )
    assert_test(test_case, [ToolCorrectnessMetric()])
