import json
from typing import Any, Optional
from unittest.mock import patch

from langchain_core import messages
from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableLambda
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from ee.models.assistant import Conversation
from posthog.schema import AssistantMessage, HumanMessage, ReasoningMessage
from posthog.test.base import NonAtomicBaseTest

from ..assistant import Assistant
from ..graph import AssistantGraph, AssistantNodeName


class TestAssistant(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def _run_assistant_graph(
        self,
        test_graph: Optional[CompiledStateGraph] = None,
        message: Optional[str] = "Hello",
        conversation: Optional[Conversation] = None,
        is_new_conversation: bool = False,
    ) -> list[tuple[str, Any]]:
        # Create assistant instance with our test graph
        assistant = Assistant(
            self.team,
            conversation,
            HumanMessage(content=message),
            self.user,
            is_new_conversation=is_new_conversation,
        )
        if test_graph:
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
            msg_dict = (
                expected_msg.model_dump(exclude_none=True) if isinstance(expected_msg, BaseModel) else expected_msg
            )
            self.assertDictContainsSubset(msg_dict, output_msg, f"Message content mismatch at index {i}")

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
            .compile(),
            conversation=self.conversation,
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
            .compile(),
            conversation=self.conversation,
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

    def _test_human_in_the_loop(self, graph: CompiledStateGraph):
        with patch("ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as mock:
            config = {
                "configurable": {
                    "thread_id": self.conversation.id,
                }
            }

            # Interrupt the graph
            message = """
            Thought: Let's ask for help.
            Action:
            ```
            {
                "action": "ask_user_for_help",
                "action_input": "Need help with this query"
            }
            ```
            """
            mock.return_value = RunnableLambda(lambda _: messages.AIMessage(content=message))
            output = self._run_assistant_graph(graph, conversation=self.conversation)
            expected_output = [
                ("message", HumanMessage(content="Hello")),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
                ("message", AssistantMessage(content="Need help with this query")),
            ]
            self.assertConversationEqual(output, expected_output)
            snapshot: StateSnapshot = graph.get_state(config)
            self.assertTrue(snapshot.next)
            self.assertIn("intermediate_steps", snapshot.values)

            # Resume the graph from the interruption point.
            message = """
            Thought: Finish.
            Action:
            ```
            {
                "action": "final_answer",
                "action_input": "Plan"
            }
            ```
            """
            mock.return_value = RunnableLambda(lambda _: messages.AIMessage(content=message))
            output = self._run_assistant_graph(graph, conversation=self.conversation, message="It's straightforward")
            expected_output = [
                ("message", HumanMessage(content="It's straightforward")),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ]
            self.assertConversationEqual(output, expected_output)
            snapshot: StateSnapshot = graph.get_state(config)
            self.assertFalse(snapshot.next)
            self.assertIsNone(snapshot.values.get("intermediate_steps"))
            self.assertEqual(snapshot.values["plan"], "Plan")

    def test_trends_interrupt_when_asking_for_help(self):
        graph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
            .add_trends_planner(AssistantNodeName.END)
            .compile()
        )
        self._test_human_in_the_loop(graph)

    def test_funnels_interrupt_when_asking_for_help(self):
        graph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_PLANNER)
            .add_funnel_planner(AssistantNodeName.END)
            .compile()
        )
        self._test_human_in_the_loop(graph)

    def test_intermediate_steps_are_updated_after_feedback(self):
        with patch("ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as mock:
            graph = (
                AssistantGraph(self.team)
                .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
                .add_trends_planner(AssistantNodeName.END)
                .compile()
            )
            config = {
                "configurable": {
                    "thread_id": self.conversation.id,
                }
            }

            # Interrupt the graph
            message = """
            Thought: Let's ask for help.
            Action:
            ```
            {
                "action": "ask_user_for_help",
                "action_input": "Need help with this query"
            }
            ```
            """
            mock.return_value = RunnableLambda(lambda _: messages.AIMessage(content=message))
            self._run_assistant_graph(graph, conversation=self.conversation)
            snapshot: StateSnapshot = graph.get_state(config)
            self.assertTrue(snapshot.next)
            self.assertIn("intermediate_steps", snapshot.values)
            self.assertEqual(len(snapshot.values["intermediate_steps"]), 1)
            action, observation = snapshot.values["intermediate_steps"][0]
            self.assertEqual(action.tool, "ask_user_for_help")
            self.assertIsNone(observation)

            self._run_assistant_graph(graph, conversation=self.conversation, message="It's straightforward")
            snapshot: StateSnapshot = graph.get_state(config)
            self.assertTrue(snapshot.next)
            self.assertIn("intermediate_steps", snapshot.values)
            self.assertEqual(len(snapshot.values["intermediate_steps"]), 2)
            action, observation = snapshot.values["intermediate_steps"][0]
            self.assertEqual(action.tool, "ask_user_for_help")
            self.assertEqual(observation, "It's straightforward")
            action, observation = snapshot.values["intermediate_steps"][1]
            self.assertEqual(action.tool, "ask_user_for_help")
            self.assertIsNone(observation)

    def test_new_conversation_handles_serialized_conversation(self):
        graph = (
            AssistantGraph(self.team)
            .add_node(AssistantNodeName.ROUTER, lambda _: {"messages": [AssistantMessage(content="Hello")]})
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROUTER)
            .add_edge(AssistantNodeName.ROUTER, AssistantNodeName.END)
            .compile()
        )
        output = self._run_assistant_graph(
            graph,
            conversation=self.conversation,
            is_new_conversation=True,
        )
        expected_output = [
            ("conversation", {"id": str(self.conversation.id)}),
        ]
        self.assertConversationEqual(output[:1], expected_output)

        output = self._run_assistant_graph(
            graph,
            conversation=self.conversation,
            is_new_conversation=False,
        )
        self.assertNotEqual(output[0][0], "conversation")
