import json
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from langchain_core.agents import AgentAction
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.utils import Conversation
from posthog.schema import AssistantMessage, HumanMessage
from posthog.test.base import NonAtomicBaseTest

from ..assistant import Assistant
from ..graph import AssistantGraph, AssistantNodeName


class TestAssistant(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _run_assistant_graph(self, test_graph: CompiledStateGraph) -> list[tuple[str, Any]]:
        # Create assistant instance with our test graph
        assistant = Assistant(
            team=self.team,
            user=self.user,
            conversation=Conversation(messages=[HumanMessage(content="Hello")], session_id=str(uuid4())),
        )
        assistant._graph = test_graph
        # Capture and parse output of assistant.stream()
        output: list[tuple[str, Any]] = []
        for message in assistant.stream():
            event_line, data_line, *_ = message.split("\n")
            output.append((event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
        return output

    def assertConversationEqual(self, output: list[tuple[str, Any]], expected_output: list[tuple[str, Any]]):
        for i, ((output_msg_type, output_msg), (expected_msg_type, expected_msg)) in enumerate(
            zip(output, expected_output)
        ):
            self.assertEqual(output_msg_type, expected_msg_type, f"Message type mismatch at index {i}")
            self.assertDictContainsSubset(expected_msg, output_msg, f"Message content mismatch at index {i}")

    @patch(
        "ee.hogai.trends.nodes.TrendsPlannerNode.run",
        return_value={"intermediate_steps": [(AgentAction(tool="final_answer", tool_input="", log=""), None)]},
    )
    @patch(
        "ee.hogai.summarizer.nodes.SummarizerNode.run", return_value={"messages": [AssistantMessage(content="Foobar")]}
    )
    def test_reasoning_messages_added(self, _mock_summarizer_run, _mock_funnel_planner_run):
        output = self._run_assistant_graph(
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
            .add_trends_planner(AssistantNodeName.SUMMARIZER)
            .add_summarizer(AssistantNodeName.END)
            .compile()
        )

        # Assert that ReasoningMessages are added
        expected_output = [
            (
                "message",
                HumanMessage(content="Hello").model_dump(exclude_none=True),
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",  # For TrendsPlannerNode
                    "substeps": [],
                },
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",  # For TrendsPlannerToolsNode
                    "substeps": [],
                },
            ),
            (
                "message",
                {
                    "type": "ai",
                    "content": "Foobar",  # Summarizer merits no ReasoningMessage, we output its results outright
                },
            ),
        ]
        self.assertConversationEqual(output, expected_output)

    @patch(
        "ee.hogai.trends.nodes.TrendsPlannerNode.run",
        return_value={
            "intermediate_steps": [
                # Compare with toolkit.py to see supported AgentAction shapes. The list below is supposed to include ALL
                (AgentAction(tool="retrieve_entity_properties", tool_input="session", log=""), None),
                (AgentAction(tool="retrieve_event_properties", tool_input="$pageview", log=""), None),
                (
                    AgentAction(
                        tool="retrieve_event_property_values",
                        tool_input={"event_name": "purchase", "property_name": "currency"},
                        log="",
                    ),
                    None,
                ),
                (
                    AgentAction(
                        tool="retrieve_entity_property_values",
                        tool_input={"entity": "person", "property_name": "country_of_birth"},
                        log="",
                    ),
                    None,
                ),
                (AgentAction(tool="handle_incorrect_response", tool_input="", log=""), None),
                (AgentAction(tool="final_answer", tool_input="", log=""), None),
            ]
        },
    )
    def test_reasoning_messages_with_substeps_added(self, _mock_funnel_planner_run):
        output = self._run_assistant_graph(
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
            .add_trends_planner(AssistantNodeName.END)
            .compile()
        )

        # Assert that ReasoningMessages are added
        expected_output = [
            (
                "message",
                HumanMessage(content="Hello").model_dump(exclude_none=True),
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",  # For TrendsPlannerNode
                    "substeps": [],
                },
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",  # For TrendsPlannerToolsNode
                    "substeps": [
                        "Exploring session properties",
                        "Exploring `$pageview` event's properties",
                        "Analyzing `currency` event's property `purchase`",
                        "Analyzing person property `country_of_birth`",
                    ],
                },
            ),
        ]
        self.assertConversationEqual(output, expected_output)
