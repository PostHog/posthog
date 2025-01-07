import json
from typing import Any, Optional, cast
from unittest.mock import patch

import pytest
from langchain_core import messages
from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from ee.hogai.funnels.nodes import FunnelsSchemaGeneratorOutput
from ee.hogai.memory import prompts as memory_prompts
from ee.hogai.router.nodes import RouterOutput
from ee.hogai.trends.nodes import TrendsSchemaGeneratorOutput
from ee.models.assistant import Conversation, CoreMemory
from posthog.schema import (
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RouterMessage,
    VisualizationMessage,
)
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event, _create_person

from ..assistant import Assistant
from ..graph import AssistantGraph, AssistantNodeName


class TestAssistant(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            text="Initial memory.",
            initial_text="Initial memory.",
            scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
        )

    def _set_up_onboarding_tests(self):
        self.core_memory.delete()
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$host": "us.posthog.com"},
        )

    def _parse_stringified_message(self, message: str) -> tuple[str, Any]:
        event_line, data_line, *_ = cast(str, message).split("\n")
        return (event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))

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
            conversation or self.conversation,
            HumanMessage(content=message),
            self.user,
            is_new_conversation=is_new_conversation,
        )
        if test_graph:
            assistant._graph = test_graph
        # Capture and parse output of assistant.stream()
        output: list[tuple[str, Any]] = []
        for message in assistant.stream():
            output.append(self._parse_stringified_message(message))
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
        return_value={"intermediate_steps": [(AgentAction(tool="final_answer", tool_input="Plan", log=""), None)]},
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
                (AgentAction(tool="final_answer", tool_input="Plan", log=""), None),
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
            config: RunnableConfig = {
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
            self.assertEqual(snapshot.values.get("intermediate_steps"), [])
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

    def test_messages_are_updated_after_feedback(self):
        with patch("ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as mock:
            graph = (
                AssistantGraph(self.team)
                .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
                .add_trends_planner(AssistantNodeName.END)
                .compile()
            )
            config: RunnableConfig = {
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
            self.assertNotIn("resumed", snapshot.values)

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
            self.assertFalse(snapshot.values["resumed"])

    def test_resuming_uses_saved_state(self):
        with patch("ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as mock:
            graph = (
                AssistantGraph(self.team)
                .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_PLANNER)
                .add_funnel_planner(AssistantNodeName.END)
                .compile()
            )
            config: RunnableConfig = {
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
            state: StateSnapshot = graph.get_state(config).values
            self.assertIn("start_id", state)
            self.assertIsNotNone(state["start_id"])

            self._run_assistant_graph(graph, conversation=self.conversation, message="It's straightforward")
            state: StateSnapshot = graph.get_state(config).values
            self.assertIn("start_id", state)
            self.assertIsNotNone(state["start_id"])

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

    @pytest.mark.asyncio
    async def test_async_stream(self):
        graph = (
            AssistantGraph(self.team)
            .add_node(AssistantNodeName.ROUTER, lambda _: {"messages": [AssistantMessage(content="bar")]})
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROUTER)
            .add_edge(AssistantNodeName.ROUTER, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant(self.team, self.conversation, HumanMessage(content="foo"))
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
            ("message", ReasoningMessage(content="Identifying type of analysis")),
            ("message", AssistantMessage(content="bar")),
        ]
        actual_output = [self._parse_stringified_message(message) async for message in assistant._astream()]
        self.assertConversationEqual(actual_output, expected_output)

    @pytest.mark.asyncio
    async def test_async_stream_handles_exceptions(self):
        def node_handler(state):
            raise ValueError()

        graph = (
            AssistantGraph(self.team)
            .add_node(AssistantNodeName.ROUTER, node_handler)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROUTER)
            .add_edge(AssistantNodeName.ROUTER, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant(self.team, self.conversation, HumanMessage(content="foo"))
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
            ("message", ReasoningMessage(content="Identifying type of analysis")),
            ("message", FailureMessage()),
        ]
        actual_output = []
        with self.assertRaises(ValueError):
            async for message in assistant._astream():
                actual_output.append(self._parse_stringified_message(message))
        self.assertConversationEqual(actual_output, expected_output)

    @patch("ee.hogai.summarizer.nodes.SummarizerNode._model")
    @patch("ee.hogai.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.router.nodes.RouterNode._model")
    @patch("ee.hogai.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_full_trends_flow(self, memory_collector_mock, router_mock, planner_mock, generator_mock, summarizer_mock):
        router_mock.return_value = RunnableLambda(lambda _: RouterOutput(visualization_type="trends"))
        planner_mock.return_value = RunnableLambda(
            lambda _: messages.AIMessage(
                content="""
                Thought: Done.
                Action:
                ```
                {
                    "action": "final_answer",
                    "action_input": "Plan"
                }
                ```
                """
            )
        )
        query = AssistantTrendsQuery(series=[])
        generator_mock.return_value = RunnableLambda(lambda _: TrendsSchemaGeneratorOutput(query=query))
        summarizer_mock.return_value = RunnableLambda(lambda _: AssistantMessage(content="Summary"))

        # First run
        actual_output = self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", {"id": str(self.conversation.id)}),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Identifying type of analysis")),
            ("message", RouterMessage(content="trends")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating trends query")),
            ("message", VisualizationMessage(answer=query, plan="Plan")),
            ("message", AssistantMessage(content="Summary")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1]["id"], actual_output[7][1]["initiator"])

        # Second run
        actual_output = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[6][1]["initiator"])

        # Third run
        actual_output = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[6][1]["initiator"])

    @patch("ee.hogai.summarizer.nodes.SummarizerNode._model")
    @patch("ee.hogai.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.router.nodes.RouterNode._model")
    @patch("ee.hogai.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_full_funnel_flow(self, memory_collector_mock, router_mock, planner_mock, generator_mock, summarizer_mock):
        router_mock.return_value = RunnableLambda(lambda _: RouterOutput(visualization_type="funnel"))
        planner_mock.return_value = RunnableLambda(
            lambda _: messages.AIMessage(
                content="""
                Thought: Done.
                Action:
                ```
                {
                    "action": "final_answer",
                    "action_input": "Plan"
                }
                ```
                """
            )
        )
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview"),
                AssistantFunnelsEventsNode(event="$pageleave"),
            ]
        )
        generator_mock.return_value = RunnableLambda(lambda _: FunnelsSchemaGeneratorOutput(query=query))
        summarizer_mock.return_value = RunnableLambda(lambda _: AssistantMessage(content="Summary"))

        # First run
        actual_output = self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", {"id": str(self.conversation.id)}),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Identifying type of analysis")),
            ("message", RouterMessage(content="funnel")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating funnel query")),
            ("message", VisualizationMessage(answer=query, plan="Plan")),
            ("message", AssistantMessage(content="Summary")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1]["id"], actual_output[7][1]["initiator"])

        # Second run
        actual_output = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[6][1]["initiator"])

        # Third run
        actual_output = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[6][1]["initiator"])

    @patch("ee.hogai.memory.nodes.MemoryInitializerInterruptNode._model")
    @patch("ee.hogai.memory.nodes.MemoryInitializerNode._model")
    def test_onboarding_flow_accepts_memory(self, model_mock, interruption_model_mock):
        self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")
        interruption_model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")

        # Create a graph with memory initialization flow
        graph = AssistantGraph(self.team).add_memory_initializer(AssistantNodeName.END).compile()

        # First run - get the product description
        output = self._run_assistant_graph(graph, is_new_conversation=True)
        expected_output = [
            ("conversation", {"id": str(self.conversation.id)}),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_INITIAL_MESSAGE,
                ),
            ),
            ("message", AssistantMessage(content="PostHog is a product analytics platform.")),
            ("message", AssistantMessage(content=memory_prompts.SCRAPING_VERIFICATION_MESSAGE)),
        ]
        self.assertConversationEqual(output, expected_output)

        # Second run - accept the memory
        output = self._run_assistant_graph(
            graph,
            message=memory_prompts.SCRAPING_CONFIRMATION_MESSAGE,
            is_new_conversation=False,
        )
        expected_output = [
            ("message", HumanMessage(content=memory_prompts.SCRAPING_CONFIRMATION_MESSAGE)),
            (
                "message",
                AssistantMessage(content=memory_prompts.SCRAPING_MEMORY_SAVED_MESSAGE),
            ),
            ("message", ReasoningMessage(content="Identifying type of analysis")),
        ]
        self.assertConversationEqual(output, expected_output)

        # Verify the memory was saved
        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.COMPLETED)
        self.assertIsNotNone(core_memory.text)

    @patch("ee.hogai.memory.nodes.MemoryInitializerNode._model")
    def test_onboarding_flow_rejects_memory(self, model_mock):
        self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")

        # Create a graph with memory initialization flow
        graph = AssistantGraph(self.team).add_memory_initializer(AssistantNodeName.END).compile()

        # First run - get the product description
        output = self._run_assistant_graph(graph, is_new_conversation=True)
        expected_output = [
            ("conversation", {"id": str(self.conversation.id)}),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_INITIAL_MESSAGE,
                ),
            ),
            ("message", AssistantMessage(content="PostHog is a product analytics platform.")),
            ("message", AssistantMessage(content=memory_prompts.SCRAPING_VERIFICATION_MESSAGE)),
        ]
        self.assertConversationEqual(output, expected_output)

        # Second run - reject the memory
        output = self._run_assistant_graph(
            graph,
            message=memory_prompts.SCRAPING_REJECTION_MESSAGE,
            is_new_conversation=False,
        )
        expected_output = [
            ("message", HumanMessage(content=memory_prompts.SCRAPING_REJECTION_MESSAGE)),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_TERMINATION_MESSAGE,
                ),
            ),
            ("message", ReasoningMessage(content="Identifying type of analysis")),
        ]
        self.assertConversationEqual(output, expected_output)

        # Verify the memory was skipped
        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.SKIPPED)
        self.assertEqual(core_memory.text, "")

    @patch("ee.hogai.memory.nodes.MemoryCollectorNode._model")
    def test_memory_collector_flow(self, model_mock):
        # Create a graph with just memory collection
        graph = (
            AssistantGraph(self.team).add_memory_collector(AssistantNodeName.END).add_memory_collector_tools().compile()
        )

        # Mock the memory collector to first analyze and then append memory
        def memory_collector_side_effect(prompt):
            prompt_messages = prompt.to_messages()
            if len(prompt_messages) == 2:  # First run
                return messages.AIMessage(
                    content="Let me analyze that.",
                    tool_calls=[
                        {
                            "id": "1",
                            "name": "core_memory_append",
                            "args": {"memory_content": "The product uses a subscription model."},
                        }
                    ],
                )
            else:  # Second run
                return messages.AIMessage(content="Processing complete. [Done]")

        model_mock.return_value = RunnableLambda(memory_collector_side_effect)

        # First run - analyze and append memory
        output = self._run_assistant_graph(
            graph,
            message="We use a subscription model",
            is_new_conversation=True,
        )
        expected_output = [
            ("conversation", {"id": str(self.conversation.id)}),
            ("message", HumanMessage(content="We use a subscription model")),
            ("message", AssistantMessage(content="Let me analyze that.")),
            ("message", AssistantMessage(content="Memory appended.")),
        ]
        self.assertConversationEqual(output, expected_output)

        # Verify memory was appended
        self.core_memory.refresh_from_db()
        self.assertIn("The product uses a subscription model.", self.core_memory.text)
