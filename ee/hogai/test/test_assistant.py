import json
from itertools import cycle
from typing import Any, Literal, Optional, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.test import override_settings
from langchain_core import messages
from langchain_core.agents import AgentAction
from langchain_core.prompts.chat import ChatPromptValue
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.errors import GraphRecursionError, NodeInterrupt
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.graph.funnels.nodes import FunnelsSchemaGeneratorOutput
from ee.hogai.graph.memory import prompts as memory_prompts
from ee.hogai.graph.retention.nodes import RetentionSchemaGeneratorOutput
from ee.hogai.graph.root.nodes import search_documentation
from ee.hogai.graph.trends.nodes import TrendsSchemaGeneratorOutput
from ee.hogai.utils.tests import FakeChatOpenAI, FakeRunnableLambdaWithTokenCounter
from ee.hogai.utils.types import AssistantMode, AssistantNodeName, AssistantState, PartialAssistantState
from ee.models.assistant import Conversation, CoreMemory
from posthog.models import Action
from posthog.schema import (
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionActionsNode,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    VisualizationMessage,
)
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event, _create_person

from ee.hogai.graph.memory import prompts as onboarding_prompts
from ..assistant import Assistant
from ..graph import AssistantGraph, InsightsAssistantGraph

title_generator_mock = patch(
    "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
    return_value=FakeChatOpenAI(responses=[messages.AIMessage(content="Title")]),
)


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
        tool_call_partial_state: Optional[AssistantState] = None,
        is_new_conversation: bool = False,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        contextual_tools: Optional[dict[str, Any]] = None,
    ) -> tuple[list[tuple[str, Any]], Assistant]:
        # Create assistant instance with our test graph
        assistant = Assistant(
            self.team,
            conversation or self.conversation,
            new_message=HumanMessage(content=message or "Hello"),
            user=self.user,
            is_new_conversation=is_new_conversation,
            tool_call_partial_state=tool_call_partial_state,
            mode=mode,
            contextual_tools=contextual_tools,
        )
        if test_graph:
            assistant._graph = test_graph
        # Capture and parse output of assistant.stream()
        output: list[tuple[str, Any]] = []
        for _message in assistant.stream():
            output.append(self._parse_stringified_message(_message))
        return output, assistant

    def assertConversationEqual(self, output: list[tuple[str, Any]], expected_output: list[tuple[str, Any]]):
        self.assertEqual(len(output), len(expected_output), output)
        for i, ((output_msg_type, output_msg), (expected_msg_type, expected_msg)) in enumerate(
            zip(output, expected_output)
        ):
            if output_msg_type == "conversation" and expected_msg_type == "conversation":
                self.assertConversationDictsEqual(output_msg, expected_msg)
            else:
                self.assertEqual(output_msg_type, expected_msg_type, f"Message type mismatch at index {i}")
                msg_dict = (
                    expected_msg.model_dump(exclude_none=True) if isinstance(expected_msg, BaseModel) else expected_msg
                )
                self.assertDictContainsSubset(msg_dict, output_msg, f"Message content mismatch at index {i}")

    def assertConversationDictsEqual(self, dict1: dict[str, Any], dict2: dict[str, Any]):
        self.assertEqual(dict1["id"], dict2["id"])
        self.assertEqual(dict1["status"], dict2["status"])
        self.assertEqual(dict1["title"], dict2["title"])
        self.assertIn("created_at", dict1)
        self.assertIn("created_at", dict2)
        self.assertIn("updated_at", dict1)
        self.assertIn("updated_at", dict2)

    def _serialize_conversation(self, conversation: Conversation | None = None) -> dict[str, Any]:
        conversation = conversation or self.conversation
        return {
            **ConversationMinimalSerializer(conversation).data,
            # Status is set in progress because conversation was generating.
            "status": Conversation.Status.IN_PROGRESS,
        }

    def assertStateMessagesEqual(self, messages: list[Any], expected_messages: list[Any]):
        self.assertEqual(len(messages), len(expected_messages))
        for i, (message, expected_message) in enumerate(zip(messages, expected_messages)):
            expected_msg_dict = (
                expected_message.model_dump(exclude_none=True)
                if isinstance(expected_message, BaseModel)
                else expected_message
            )
            msg_dict = message.model_dump(exclude_none=True) if isinstance(message, BaseModel) else message
            self.assertDictContainsSubset(expected_msg_dict, msg_dict, f"Message content mismatch at index {i}")

    @patch(
        "ee.hogai.graph.trends.nodes.TrendsPlannerNode.run",
        return_value=PartialAssistantState(
            intermediate_steps=[
                (AgentAction(tool="final_answer", tool_input="Plan", log=""), None),
            ],
        ),
    )
    @patch(
        "ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run",
        return_value=PartialAssistantState(
            messages=[AssistantMessage(content="Foobar")],
        ),
    )
    def test_reasoning_messages_added(self, _mock_query_executor_run, _mock_funnel_planner_run):
        output, _ = self._run_assistant_graph(
            InsightsAssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
            .add_trends_planner(AssistantNodeName.QUERY_EXECUTOR, AssistantNodeName.END)
            .add_query_executor(AssistantNodeName.END)
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
        ]
        self.assertConversationEqual(output, expected_output)

    @patch(
        "ee.hogai.graph.trends.nodes.TrendsPlannerNode.run",
        return_value=PartialAssistantState(
            intermediate_steps=[
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
        ),
    )
    def test_reasoning_messages_with_substeps_added(self, _mock_funnel_planner_run):
        output, _ = self._run_assistant_graph(
            InsightsAssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
            .add_trends_planner(AssistantNodeName.END, AssistantNodeName.END)
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

    def test_action_reasoning_messages_added(self):
        action = Action.objects.create(team=self.team, name="Marius Tech Tips")

        with patch(
            "ee.hogai.graph.trends.nodes.TrendsPlannerNode.run",
            return_value=PartialAssistantState(
                intermediate_steps=[
                    (
                        AgentAction(
                            tool="retrieve_action_properties",
                            # String is expected here.
                            tool_input=str(action.id),
                            log="",
                        ),
                        None,
                    ),
                    (
                        AgentAction(
                            tool="retrieve_action_property_values",
                            tool_input={"action_id": action.id, "property_name": "video_name"},
                            log="",
                        ),
                        None,
                    ),
                    (AgentAction(tool="final_answer", tool_input="Plan", log=""), None),
                ]
            ),
        ):
            output, _ = self._run_assistant_graph(
                InsightsAssistantGraph(self.team)
                .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
                .add_trends_planner(AssistantNodeName.END, AssistantNodeName.END)
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
                            "Exploring `Marius Tech Tips` action properties",
                            "Analyzing `video_name` action property of `Marius Tech Tips`",
                        ],
                    },
                ),
            ]
            self.assertConversationEqual(output, expected_output)

    def _test_human_in_the_loop(self, insight_type: Literal["trends", "funnel", "retention"]):
        graph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root(
                {
                    "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
                    "root": AssistantNodeName.ROOT,
                    "end": AssistantNodeName.END,
                }
            )
            .add_insights(AssistantNodeName.ROOT)
            .compile()
        )

        with (
            patch("ee.hogai.graph.root.nodes.RootNode._get_model") as root_mock,
            patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as planner_mock,
        ):
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": self.conversation.id,
                }
            }

            def root_side_effect(prompt: ChatPromptValue):
                if prompt.messages[-1].type == "tool":
                    return RunnableLambda(lambda _: messages.AIMessage(content="Agent needs help with this query"))

                return messages.AIMessage(
                    content="Okay",
                    tool_calls=[
                        {
                            "id": "1",
                            "name": "create_and_query_insight",
                            "args": {"query_description": "Foobar", "query_kind": insight_type},
                        }
                    ],
                )

            root_mock.return_value = FakeRunnableLambdaWithTokenCounter(root_side_effect)

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
            planner_mock.return_value = RunnableLambda(lambda _: messages.AIMessage(content=message))
            output, _ = self._run_assistant_graph(graph, conversation=self.conversation)
            expected_output = [
                ("message", HumanMessage(content="Hello")),
                ("message", AssistantMessage(content="Okay")),
                ("message", ReasoningMessage(content="Coming up with an insight")),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
                ("message", AssistantMessage(content="Agent needs help with this query")),
            ]
            self.assertConversationEqual(output, expected_output)
            snapshot: StateSnapshot = graph.get_state(config)
            self.assertFalse(snapshot.next)
            self.assertFalse(snapshot.values.get("intermediate_steps"))
            self.assertFalse(snapshot.values["plan"])
            self.assertFalse(snapshot.values["graph_status"])
            self.assertFalse(snapshot.values["root_tool_call_id"])
            self.assertFalse(snapshot.values["root_tool_insight_plan"])
            self.assertFalse(snapshot.values["root_tool_insight_type"])
            self.assertFalse(snapshot.values["root_tool_calls_count"])

    def test_trends_interrupt_when_asking_for_help(self):
        self._test_human_in_the_loop("trends")

    def test_funnels_interrupt_when_asking_for_help(self):
        self._test_human_in_the_loop("funnel")

    def test_retention_interrupt_when_asking_for_help(self):
        self._test_human_in_the_loop("retention")

    def test_ai_messages_appended_after_interrupt(self):
        with patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as mock:
            graph = (
                InsightsAssistantGraph(self.team)
                .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_PLANNER)
                .add_trends_planner(AssistantNodeName.END, AssistantNodeName.END)
                .compile()
            )
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": self.conversation.id,
                }
            }

            def interrupt_graph(_):
                raise NodeInterrupt("test")

            mock.return_value = RunnableLambda(interrupt_graph)
            self._run_assistant_graph(graph, conversation=self.conversation)
            snapshot: StateSnapshot = graph.get_state(config)
            self.assertTrue(snapshot.next)
            self.assertEqual(snapshot.values["graph_status"], "interrupted")
            self.assertIsInstance(snapshot.values["messages"][-1], AssistantMessage)
            self.assertEqual(snapshot.values["messages"][-1].content, "test")

            def interrupt_graph(_):
                self.assertEqual(graph.get_state(config).values["graph_status"], "resumed")
                raise NodeInterrupt("test")

            mock.return_value = RunnableLambda(interrupt_graph)
            self._run_assistant_graph(graph, conversation=self.conversation)

    def test_recursion_error_is_handled(self):
        class FakeStream:
            def __init__(self, *args, **kwargs):
                pass

            def __iter__(self):
                raise GraphRecursionError()

        with patch("langgraph.pregel.Pregel.stream", side_effect=FakeStream):
            output, _ = self._run_assistant_graph(conversation=self.conversation)
            self.assertEqual(output[0][0], "message")
            self.assertEqual(output[0][1]["content"], "Hello")
            self.assertEqual(output[1][0], "message")
            self.assertEqual(
                output[1][1]["content"],
                "The assistant has reached the maximum number of steps. You can explicitly ask to continue.",
            )

    def test_new_conversation_handles_serialized_conversation(self):
        graph = (
            AssistantGraph(self.team)
            .add_node(AssistantNodeName.ROOT, lambda _: {"messages": [AssistantMessage(content="Hello")]})
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        output, _ = self._run_assistant_graph(
            graph,
            conversation=self.conversation,
            is_new_conversation=True,
        )
        expected_output = [
            ("conversation", self._serialize_conversation()),
        ]
        self.assertConversationEqual(output[:1], expected_output)

        output, _ = self._run_assistant_graph(
            graph,
            conversation=self.conversation,
            is_new_conversation=False,
        )
        self.assertNotEqual(output[0][0], "conversation")

    @pytest.mark.asyncio
    async def test_async_stream(self):
        graph = (
            AssistantGraph(self.team)
            .add_node(AssistantNodeName.ROOT, lambda _: {"messages": [AssistantMessage(content="bar")]})
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant(self.team, self.conversation, new_message=HumanMessage(content="foo"))
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
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
            .add_node(AssistantNodeName.ROOT, node_handler)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant(self.team, self.conversation, new_message=HumanMessage(content="foo"))
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
            ("message", FailureMessage()),
        ]
        actual_output = []
        with self.assertRaises(ValueError):
            async for message in assistant._astream():
                actual_output.append(self._parse_stringified_message(message))
        self.assertConversationEqual(actual_output, expected_output)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_full_trends_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        res1 = FakeRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar", "query_kind": "trends"},
                    }
                ],
            )
        )
        res2 = FakeRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res1, res2, res2])

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

        # First run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating trends query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1]["id"], actual_output[6][1]["initiator"])  # viz message must have this id

        # Second run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[5][1]["initiator"])

        # Third run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[5][1]["initiator"])

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_full_funnel_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        res1 = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "create_and_query_insight",
                            "args": {"query_description": "Foobar", "query_kind": "funnel"},
                        }
                    ],
                )
            ]
        )
        res2 = FakeChatOpenAI(
            responses=[messages.AIMessage(content="The results indicate a great future for you.")],
        )
        root_mock.side_effect = cycle([res1, res1, res2, res2])

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

        # First run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating funnel query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1]["id"], actual_output[6][1]["initiator"])  # viz message must have this id

        # Second run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[5][1]["initiator"])

        # Third run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[5][1]["initiator"])

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_full_retention_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        action = Action.objects.create(team=self.team, name="Marius Tech Tips")

        res1 = FakeRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar", "query_kind": "retention"},
                    }
                ],
            )
        )
        res2 = FakeRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res1, res2, res2])

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
        query = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity=AssistantRetentionEventsNode(name="$pageview"),
                returningEntity=AssistantRetentionActionsNode(name=action.name, id=action.id),
            )
        )
        generator_mock.return_value = RunnableLambda(lambda _: RetentionSchemaGeneratorOutput(query=query))

        # First run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating retention query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1]["id"], actual_output[6][1]["initiator"])  # viz message must have this id

        # Second run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[5][1]["initiator"])

        # Third run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1]["id"], actual_output[5][1]["initiator"])

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_full_sql_flow(self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock):
        res1 = FakeRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar", "query_kind": "sql"},
                    }
                ],
            )
        )
        res2 = FakeRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res1, res2, res2])

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
        query = AssistantHogQLQuery(query="SELECT 1")
        generator_mock.return_value = RunnableLambda(lambda _: query.model_dump())

        # First run
        actual_output, _ = self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating SQL query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1]["id"], actual_output[6][1]["initiator"])  # viz message must have this id

    @patch("ee.hogai.graph.memory.nodes.MemoryOnboardingEnquiryNode._model")
    @patch("ee.hogai.graph.memory.nodes.MemoryInitializerNode._model")
    def test_onboarding_flow_accepts_memory(self, model_mock, onboarding_enquiry_model_mock):
        self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")

        def mock_response(input_dict):
            input_str = str(input_dict)
            if "You are tasked with gathering information" in input_str:
                return "===What is your target market?"
            return "[Done]"

        onboarding_enquiry_model_mock.return_value = RunnableLambda(mock_response)

        # Create a graph with memory initialization flow
        graph = AssistantGraph(self.team).add_memory_onboarding(AssistantNodeName.END, AssistantNodeName.END).compile()

        # First run - get the product description
        output, _ = self._run_assistant_graph(
            graph, is_new_conversation=True, message=onboarding_prompts.ONBOARDING_INITIAL_MESSAGE
        )
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content=onboarding_prompts.ONBOARDING_INITIAL_MESSAGE)),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_INITIAL_MESSAGE,
                ),
            ),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_SUCCESS_MESSAGE + "PostHog is a product analytics platform."
                ),
            ),
            ("message", AssistantMessage(content=memory_prompts.SCRAPING_VERIFICATION_MESSAGE)),
        ]
        self.assertConversationEqual(output, expected_output)

        # Second run - accept the memory
        output, _ = self._run_assistant_graph(
            graph,
            message=memory_prompts.SCRAPING_CONFIRMATION_MESSAGE,
            is_new_conversation=False,
        )
        expected_output = [
            ("message", HumanMessage(content=memory_prompts.SCRAPING_CONFIRMATION_MESSAGE)),
            (
                "message",
                AssistantMessage(content="What is your target market?"),
            ),
        ]
        self.assertConversationEqual(output, expected_output)

        # Verify the memory was saved
        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(
            core_memory.initial_text,
            "Question: What does the company do?\nAnswer: PostHog is a product analytics platform.\nQuestion: What is your target market?\nAnswer:",
        )

    @patch("ee.hogai.graph.memory.nodes.MemoryInitializerNode._model")
    @patch("ee.hogai.graph.memory.nodes.MemoryOnboardingEnquiryNode._model")
    def test_onboarding_flow_rejects_memory(self, onboarding_enquiry_model_mock, model_mock):
        self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")
        onboarding_enquiry_model_mock.return_value = RunnableLambda(lambda _: "===What is your target market?")

        # Create a graph with memory initialization flow
        graph = AssistantGraph(self.team).add_memory_onboarding(AssistantNodeName.END, AssistantNodeName.END).compile()

        # First run - get the product description
        output, _ = self._run_assistant_graph(
            graph, is_new_conversation=True, message=onboarding_prompts.ONBOARDING_INITIAL_MESSAGE
        )
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content=onboarding_prompts.ONBOARDING_INITIAL_MESSAGE)),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_INITIAL_MESSAGE,
                ),
            ),
            (
                "message",
                AssistantMessage(
                    content=memory_prompts.SCRAPING_SUCCESS_MESSAGE + "PostHog is a product analytics platform."
                ),
            ),
            ("message", AssistantMessage(content=memory_prompts.SCRAPING_VERIFICATION_MESSAGE)),
        ]
        self.assertConversationEqual(output, expected_output)

        # Second run - reject the memory
        output, _ = self._run_assistant_graph(
            graph,
            message=memory_prompts.SCRAPING_REJECTION_MESSAGE,
            is_new_conversation=False,
        )
        expected_output = [
            ("message", HumanMessage(content=memory_prompts.SCRAPING_REJECTION_MESSAGE)),
            (
                "message",
                AssistantMessage(
                    content="What is your target market?",
                ),
            ),
        ]
        self.assertConversationEqual(output, expected_output)

        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(core_memory.initial_text, "Question: What is your target market?\nAnswer:")

    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model")
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
        output, _ = self._run_assistant_graph(
            graph,
            message="We use a subscription model",
            is_new_conversation=True,
        )
        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content="We use a subscription model")),
        ]
        self.assertConversationEqual(output, expected_output)

        # Verify memory was appended
        self.core_memory.refresh_from_db()
        self.assertIn("The product uses a subscription model.", self.core_memory.text)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    def test_exits_infinite_loop_after_fourth_attempt(
        self, memory_collector_mock, get_model_mock, planner_mock, generator_mock, title_node_mock
    ):
        """Test that the assistant exits an infinite loop of tool calls after the 4th attempt."""

        # Track number of attempts
        attempts = 0

        # Mock the root node to keep making tool calls until 4th attempt
        def make_tool_call(_):
            nonlocal attempts
            attempts += 1
            if attempts <= 4:
                return messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": str(uuid4()),
                            "name": "create_and_query_insight",
                            "args": {"query_description": "Foobar", "query_kind": "trends"},
                        }
                    ],
                )
            return messages.AIMessage(content="No more tool calls after 4th attempt")

        get_model_mock.return_value = FakeRunnableLambdaWithTokenCounter(make_tool_call)
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

        # Create a graph that only uses the root node
        graph = AssistantGraph(self.team).compile_full_graph()

        # Run the assistant and capture output
        output, _ = self._run_assistant_graph(graph)

        # Verify the last message doesn't contain any tool calls and has our expected content
        last_message = output[-1][1]
        self.assertNotIn("tool_calls", last_message, "The final message should not contain any tool calls")
        self.assertEqual(
            last_message["content"],
            "No more tool calls after 4th attempt",
            "Final message should indicate no more tool calls",
        )

    def test_conversation_is_locked_when_generating(self):
        graph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root({"root": AssistantNodeName.ROOT, "end": AssistantNodeName.END})
            .compile()
        )
        self.assertEqual(self.conversation.status, Conversation.Status.IDLE)
        with patch("ee.hogai.graph.root.nodes.RootNode._get_model") as root_mock:

            def assert_lock_status(_):
                self.assertEqual(self.conversation.status, Conversation.Status.IN_PROGRESS)
                return messages.AIMessage(content="")

            root_mock.return_value = FakeRunnableLambdaWithTokenCounter(assert_lock_status)
            self._run_assistant_graph(graph)
            self.assertEqual(self.conversation.status, Conversation.Status.IDLE)

    def test_conversation_saves_state_after_cancellation(self):
        graph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root({"root": AssistantNodeName.ROOT, "end": AssistantNodeName.END})
            .compile()
        )

        self.assertEqual(self.conversation.status, Conversation.Status.IDLE)
        with (
            patch("ee.hogai.graph.root.nodes.RootNode._get_model") as root_mock,
            patch("ee.hogai.graph.root.nodes.RootNodeTools.run") as root_tool_mock,
        ):

            def assert_lock_status(_):
                self.conversation.status = Conversation.Status.CANCELING
                self.conversation.save()
                return messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "1",
                            "name": "create_and_query_insight",
                            "args": {"query_description": "Foobar", "query_kind": "trends"},
                        }
                    ],
                )

            root_mock.return_value = FakeRunnableLambdaWithTokenCounter(assert_lock_status)
            self._run_assistant_graph(graph)
            snapshot = graph.get_state({"configurable": {"thread_id": str(self.conversation.id)}})
            self.assertEqual(snapshot.next, (AssistantNodeName.ROOT_TOOLS,))
            self.assertEqual(snapshot.values["messages"][-1].content, "")
            root_tool_mock.assert_not_called()

        with patch("ee.hogai.graph.root.nodes.RootNode._get_model") as root_mock:
            # The graph must start from the root node despite being cancelled on the root tools node.
            root_mock.return_value = FakeRunnableLambdaWithTokenCounter(
                lambda _: messages.AIMessage(content="Finished")
            )
            expected_output = [
                ("message", HumanMessage(content="Hello")),
                ("message", AssistantMessage(content="Finished")),
            ]
            actual_output, _ = self._run_assistant_graph(graph)
            self.assertConversationEqual(actual_output, expected_output)

    @override_settings(INKEEP_API_KEY="test")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode._get_model")
    def test_inkeep_docs_basic_search(self, inkeep_docs_model_mock, root_model_mock):
        """Test basic documentation search functionality using Inkeep."""
        graph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root(
                {
                    "search_documentation": AssistantNodeName.INKEEP_DOCS,
                    "root": AssistantNodeName.ROOT,
                    "end": AssistantNodeName.END,
                }
            )
            .add_inkeep_docs()
            .compile()
        )

        root_model_mock.return_value = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="", tool_calls=[{"name": search_documentation.__name__, "id": "1", "args": {}}]
                )
            ]
        )
        inkeep_docs_model_mock.return_value = FakeChatOpenAI(
            responses=[messages.AIMessage(content="Here's what I found in the docs...")]
        )
        output, _ = self._run_assistant_graph(graph, message="How do I use feature flags?")

        self.assertConversationEqual(
            output,
            [
                ("message", HumanMessage(content="How do I use feature flags?")),
                ("message", ReasoningMessage(content="Checking PostHog docs")),
                ("message", AssistantMessage(content="Here's what I found in the docs...")),
            ],
        )

    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run")
    def test_insights_tool_mode_flow(self, query_executor_mock, planner_mock, generator_mock):
        """Test that the insights tool mode works correctly."""
        query = AssistantTrendsQuery(series=[])
        tool_call_id = str(uuid4())
        tool_call_state = AssistantState(
            root_tool_call_id=tool_call_id,
            root_tool_insight_plan="Foobar",
            root_tool_insight_type="trends",
            messages=[],
        )

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
        generator_mock.return_value = RunnableLambda(lambda _: TrendsSchemaGeneratorOutput(query=query))
        query_executor_mock.return_value = RunnableLambda(
            lambda _: PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="The results indicate a great future for you.", tool_call_id=tool_call_id
                    )
                ]
            )
        )
        # Run in insights tool mode
        output, _ = self._run_assistant_graph(
            conversation=self.conversation,
            is_new_conversation=False,
            message=None,
            mode=AssistantMode.INSIGHTS_TOOL,
            tool_call_partial_state=tool_call_state,
        )

        expected_output = [
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating trends query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            (
                "message",
                AssistantToolCallMessage(
                    content="The results indicate a great future for you.", tool_call_id=tool_call_id
                ),
            ),
        ]
        self.assertConversationEqual(output, expected_output)

    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run")
    def test_insights_tool_mode_invalid_insight_type(self, query_executor_mock, planner_mock, generator_mock):
        """Test that insights tool mode handles invalid insight types correctly."""
        tool_call_state = AssistantState(
            root_tool_call_id=str(uuid4()),
            root_tool_insight_plan="Foobar",
            root_tool_insight_type="invalid_type",  # Invalid type
            messages=[],
        )

        with self.assertRaises(ValueError) as cm:
            self._run_assistant_graph(
                conversation=self.conversation,
                is_new_conversation=False,
                tool_call_partial_state=tool_call_state,
                mode=AssistantMode.INSIGHTS_TOOL,
            )
        self.assertEqual(str(cm.exception), "Invalid insight type: invalid_type")

    @patch("ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model")
    def test_conversation_metadata_updated(self, title_generator_model_mock):
        """Test that metadata (title, created_at, updated_at) is generated and set for a new conversation."""
        # Create a test graph with only the title generator node
        graph = AssistantGraph(self.team).add_title_generator().compile()
        initial_updated_at = self.conversation.updated_at
        initial_created_at = self.conversation.created_at

        self.assertIsNone(self.conversation.title)

        # Mock the title generator to return "Generated Conversation Title"
        title_generator_model_mock.return_value = FakeChatOpenAI(
            responses=[messages.AIMessage(content="Generated Conversation Title")]
        )

        # Run the assistant
        self._run_assistant_graph(
            graph,
            message="This is the first message in the conversation",
            is_new_conversation=True,
        )

        # Assert the conversation doesn't have a title yet
        self.conversation.refresh_from_db()
        # Verify the title has been set
        self.assertEqual(self.conversation.title, "Generated Conversation Title")
        assert self.conversation.updated_at is not None
        assert initial_updated_at is not None
        self.assertGreater(self.conversation.updated_at, initial_updated_at)
        self.assertEqual(self.conversation.created_at, initial_created_at)

    def test_merges_messages_with_same_id(self):
        """Test that messages with the same ID are merged into one."""
        message_id = str(uuid4())

        # Create a simple graph that will return messages with the same ID but different content
        first_content = "First version of message"
        updated_content = "Updated version of message"

        class MessageUpdatingNode:
            def __init__(self):
                self.call_count = 0

            def __call__(self, state):
                self.call_count += 1
                content = first_content if self.call_count == 1 else updated_content
                return {"messages": [AssistantMessage(id=message_id, content=content)]}

        updater = MessageUpdatingNode()
        graph = (
            AssistantGraph(self.team)
            .add_node(AssistantNodeName.ROOT, updater)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        config = {"configurable": {"thread_id": self.conversation.id}}

        # First run should add the message with initial content
        output, _ = self._run_assistant_graph(graph, conversation=self.conversation)
        self.assertEqual(len(output), 2)  # Human message + AI message
        self.assertEqual(output[1][1]["id"], message_id)
        self.assertEqual(output[1][1]["content"], first_content)

        # Second run should update the message with new content
        output, _ = self._run_assistant_graph(graph, conversation=self.conversation)
        self.assertEqual(len(output), 2)  # Human message + AI message
        self.assertEqual(output[1][1]["id"], message_id)
        self.assertEqual(output[1][1]["content"], updated_content)

        # Verify the message was actually replaced, not duplicated
        messages = graph.get_state(config).values["messages"]

        # Count messages with our test ID
        messages_with_id = [msg for msg in messages if msg.id == message_id]
        self.assertEqual(len(messages_with_id), 1, "There should be exactly one message with the test ID")
        self.assertEqual(
            messages_with_id[0].content,
            updated_content,
            "The merged message should have the content of the last message",
        )

    def test_assistant_filters_messages_correctly(self):
        """Test that the Assistant class correctly filters messages based on should_output_assistant_message."""

        output_messages = [
            # Should be output (has content)
            (AssistantMessage(content="This message has content", id="1"), True),
            # Should be filtered out (empty content)
            (AssistantMessage(content="", id="2"), False),
            # Should be output (has UI payload)
            (
                AssistantToolCallMessage(
                    content="Tool result", tool_call_id="123", id="3", ui_payload={"some": "data"}
                ),
                True,
            ),
            # Should be filtered out (no UI payload)
            (AssistantToolCallMessage(content="Tool result", tool_call_id="456", id="4", ui_payload=None), False),
        ]

        for test_message, expected_in_output in output_messages:
            # Create a simple graph that produces different message types to test filtering
            class MessageFilteringNode:
                def __init__(self, message_to_return):
                    self.message_to_return = message_to_return

                def __call__(self, *args, **kwargs):
                    # Return a set of messages that should be filtered differently
                    return PartialAssistantState(messages=[self.message_to_return])

            # Create a graph with our test node
            graph = (
                AssistantGraph(self.team)
                .add_node(AssistantNodeName.ROOT, MessageFilteringNode(test_message))
                .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                .compile()
            )

            # Run the assistant and capture output
            output, _ = self._run_assistant_graph(graph, conversation=self.conversation)
            expected_output: list = [
                ("message", HumanMessage(content="Hello")),
            ]

            if expected_in_output:
                expected_output.append(("message", test_message))

            self.assertConversationEqual(output, expected_output)

    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run")
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.rag.nodes.InsightRagContextNode.run")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    def test_create_and_query_insight_contextual_tool(
        self, root_mock, rag_mock, planner_mock, generator_mock, query_executor_mock
    ):
        def root_side_effect(prompt: ChatPromptValue):
            if prompt.messages[-1].type == "tool":
                return RunnableLambda(lambda _: messages.AIMessage(content="Everything is fine"))

            return messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar", "query_kind": "trends"},
                    }
                ],
            )

        root_mock.return_value = FakeRunnableLambdaWithTokenCounter(root_side_effect)
        rag_mock.return_value = PartialAssistantState(
            rag_context="",
        )

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

        query_executor_mock.return_value = PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content="The results indicate a great future for you.", tool_call_id="xyz")
            ],
        )

        output, assistant = self._run_assistant_graph(
            test_graph=AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root(
                {
                    "root": AssistantNodeName.ROOT,
                    "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
                    "end": AssistantNodeName.END,
                }
            )
            .add_insights()
            .compile(),
            conversation=self.conversation,
            is_new_conversation=True,
            message=None,
            mode=AssistantMode.ASSISTANT,
            contextual_tools={"create_and_query_insight": {"current_query": "query"}},
        )

        expected_output = [
            ("conversation", self._serialize_conversation()),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating trends query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            (
                "message",
                AssistantToolCallMessage(
                    content="The results indicate a great future for you.",
                    tool_call_id="xyz",
                    ui_payload={"create_and_query_insight": query.model_dump()},
                    visible=False,
                ),
            ),
            ("message", AssistantMessage(content="Everything is fine")),
        ]
        self.assertConversationEqual(output, expected_output)

        state = AssistantState.model_validate(assistant._graph.get_state(assistant._get_config()).values)
        expected_state_messages = [
            HumanMessage(content="Hello"),
            AssistantMessage(
                content="",
                tool_calls=[
                    AssistantToolCall(
                        id="xyz",
                        name="create_and_query_insight",
                        args={"query_description": "Foobar", "query_kind": "trends"},
                    )
                ],
            ),
            VisualizationMessage(query="Foobar", answer=query, plan="Plan"),
            AssistantToolCallMessage(
                content="The results indicate a great future for you.",
                tool_call_id="xyz",
                ui_payload={"create_and_query_insight": query.model_dump()},
                visible=False,
            ),
            AssistantMessage(content="Everything is fine"),
        ]
        self.assertStateMessagesEqual(state.messages, expected_state_messages)
