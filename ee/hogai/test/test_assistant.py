from itertools import cycle
from typing import Any, Literal, Optional, cast
from uuid import uuid4

from posthog.test.base import (
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from unittest.mock import AsyncMock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync, sync_to_async
from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.models import EmbeddingsResult, EmbeddingsUsage
from azure.core.credentials import AzureKeyCredential
from langchain_core import messages
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.errors import GraphRecursionError, NodeInterrupt
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from posthog.schema import (
    AssistantEventType,
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionActionsNode,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    AssistantUpdateEvent,
    ContextMessage,
    DashboardFilter,
    FailureMessage,
    HumanMessage,
    MaxAddonInfo,
    MaxBillingContext,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxDashboardContext,
    MaxInsightContext,
    MaxProductInfo,
    MaxUIContext,
    TrendsQuery,
    VisualizationMessage,
)

from posthog.models import Action

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.funnels.nodes import FunnelsSchemaGeneratorOutput
from ee.hogai.graph.memory import prompts as memory_prompts
from ee.hogai.graph.retention.nodes import RetentionSchemaGeneratorOutput
from ee.hogai.graph.root.nodes import SLASH_COMMAND_INIT
from ee.hogai.graph.trends.nodes import TrendsSchemaGeneratorOutput
from ee.hogai.utils.state import GraphValueUpdateTuple
from ee.hogai.utils.tests import FakeAnthropicRunnableLambdaWithTokenCounter, FakeChatAnthropic, FakeChatOpenAI
from ee.hogai.utils.types import (
    AssistantMode,
    AssistantNodeName,
    AssistantOutput,
    AssistantState,
    PartialAssistantState,
)
from ee.models.assistant import Conversation, CoreMemory

from ..assistant import Assistant
from ..graph import AssistantGraph, InsightsAssistantGraph

title_generator_mock = patch(
    "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
    return_value=FakeChatOpenAI(responses=[messages.AIMessage(content="Title")]),
)


class TestAssistant(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            text="Initial memory.",
            initial_text="Initial memory.",
            scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
        )

        # Azure embeddings mocks
        self.azure_client_mock = patch(
            "ee.hogai.graph.rag.nodes.get_azure_embeddings_client",
            return_value=EmbeddingsClient(
                endpoint="https://test.services.ai.azure.com/models", credential=AzureKeyCredential("test")
            ),
        ).start()
        self.embed_query_mock = patch(
            "azure.ai.inference.EmbeddingsClient.embed",
            return_value=EmbeddingsResult(
                id="test",
                model="test",
                usage=EmbeddingsUsage(prompt_tokens=1, total_tokens=1),
                data=[],
            ),
        ).start()

        self.checkpointer_patch = patch("ee.hogai.graph.graph.global_checkpointer", new=DjangoCheckpointer())
        self.checkpointer_patch.start()

    def tearDown(self):
        self.checkpointer_patch.stop()
        self.azure_client_mock.stop()
        self.embed_query_mock.stop()
        super().tearDown()

    async def _set_up_onboarding_tests(self):
        await self.core_memory.adelete()
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
        await sync_to_async(flush_persons_and_events)()

    async def _run_assistant_graph(
        self,
        test_graph: Optional[CompiledStateGraph] = None,
        message: Optional[str] = "Hello",
        conversation: Optional[Conversation] = None,
        tool_call_partial_state: Optional[AssistantState] = None,
        is_new_conversation: bool = False,
        mode: Optional[AssistantMode] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        ui_context: Optional[MaxUIContext] = None,
        filter_ack_messages: bool = True,
    ) -> tuple[list[AssistantOutput], BaseAssistant]:
        # If no mode is specified, use ASSISTANT as default
        if mode is None:
            mode = AssistantMode.ASSISTANT

        # Create assistant instance
        assistant = Assistant.create(
            self.team,
            conversation or self.conversation,
            new_message=HumanMessage(content=message, ui_context=ui_context) if message is not None else None,
            user=self.user,
            is_new_conversation=is_new_conversation,
            initial_state=tool_call_partial_state,
            mode=mode,
            contextual_tools=contextual_tools,
        )

        # Override the graph if a test graph is provided
        if test_graph:
            assistant._graph = test_graph

        # Capture and parse output of assistant.astream()
        output: list[AssistantOutput] = []
        async for event in assistant.astream():
            output.append(event)
        if filter_ack_messages:
            output = [
                event
                for event in output
                if not (
                    isinstance(event[1], AssistantGenerationStatusEvent)
                    and event[1].type == AssistantGenerationStatusType.ACK
                )
            ]
        return output, assistant

    def assertConversationEqual(self, output: list[AssistantOutput], expected_output: list[tuple[Any, Any]]):
        self.assertEqual(len(output), len(expected_output), output)
        for i, ((output_msg_type, output_msg), (expected_msg_type, expected_msg)) in enumerate(
            zip(output, expected_output)
        ):
            if (
                output_msg_type == AssistantEventType.CONVERSATION
                and expected_msg_type == AssistantEventType.CONVERSATION
            ):
                self.assertEqual(output_msg, expected_msg)
            elif (
                output_msg_type == AssistantEventType.MESSAGE and expected_msg_type == AssistantEventType.MESSAGE
            ) or (output_msg_type == AssistantEventType.UPDATE and expected_msg_type == AssistantEventType.UPDATE):
                msg_dict = (
                    expected_msg.model_dump(exclude_none=True) if isinstance(expected_msg, BaseModel) else expected_msg
                )
                msg_dict.pop("id", None)
                output_msg_dict = cast(BaseModel, output_msg).model_dump(exclude_none=True)
                output_msg_dict.pop("id", None)
                self.assertLessEqual(
                    msg_dict.items(),
                    output_msg_dict.items(),
                    f"Message content mismatch at index {i}",
                )
            else:
                raise ValueError(f"Unexpected message type: {output_msg_type} and {expected_msg_type}")

    def assertStateMessagesEqual(self, messages: list[Any], expected_messages: list[Any]):
        self.assertEqual(len(messages), len(expected_messages))
        for i, (message, expected_message) in enumerate(zip(messages, expected_messages)):
            expected_msg_dict = (
                expected_message.model_dump(exclude_none=True)
                if isinstance(expected_message, BaseModel)
                else expected_message
            )
            expected_msg_dict.pop("id", None)
            msg_dict = message.model_dump(exclude_none=True) if isinstance(message, BaseModel) else message
            msg_dict.pop("id", None)
            self.assertLessEqual(expected_msg_dict.items(), msg_dict.items(), f"Message content mismatch at index {i}")

    async def _test_human_in_the_loop(self, insight_type: Literal["trends", "funnel", "retention"]):
        graph = (
            AssistantGraph(self.team, self.user)
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
            patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model") as planner_mock,
        ):
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": self.conversation.id,
                }
            }

            def root_side_effect(msgs: list[BaseMessage]):
                last_message = msgs[-1]

                if (
                    isinstance(last_message.content, list)
                    and isinstance(last_message.content[-1], dict)
                    and last_message.content[-1]["type"] == "tool_result"
                ):
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

            root_mock.return_value = FakeAnthropicRunnableLambdaWithTokenCounter(root_side_effect)

            # Interrupt the graph
            planner_mock.return_value = FakeChatOpenAI(
                responses=[
                    messages.AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "ask_user_for_help",
                                "args": {"request": "Need help with this query"},
                            }
                        ],
                    )
                ]
            )
            output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
            expected_output = [
                ("message", HumanMessage(content="Hello")),
                (
                    "message",
                    AssistantMessage(
                        content="Okay",
                        tool_calls=[
                            AssistantToolCall(
                                id="1",
                                name="create_and_query_insight",
                                args={"query_description": "Foobar", "query_kind": insight_type},
                            )
                        ],
                    ),
                ),
                (
                    "update",
                    AssistantUpdateEvent(
                        id="message_1",
                        content="Picking relevant events and properties",
                        tool_call_id="1",
                    ),
                ),
                (
                    "message",
                    AssistantToolCallMessage(
                        content="The agent has requested help:\nrequest='Need help with this query'", tool_call_id="1"
                    ),
                ),
                ("message", AssistantMessage(content="Agent needs help with this query")),
            ]
            self.assertConversationEqual(output, expected_output)
            snapshot: StateSnapshot = await graph.aget_state(config)
            self.assertFalse(snapshot.next)
            self.assertFalse(snapshot.values.get("intermediate_steps"))
            self.assertFalse(snapshot.values["plan"])
            self.assertFalse(snapshot.values["graph_status"])
            self.assertFalse(snapshot.values["root_tool_call_id"])
            self.assertFalse(snapshot.values["root_tool_insight_plan"])
            self.assertFalse(snapshot.values["root_tool_insight_type"])
            self.assertFalse(snapshot.values["root_tool_calls_count"])

    async def test_trends_interrupt_when_asking_for_help(self):
        await self._test_human_in_the_loop("trends")

    async def test_funnels_interrupt_when_asking_for_help(self):
        await self._test_human_in_the_loop("funnel")

    async def test_retention_interrupt_when_asking_for_help(self):
        await self._test_human_in_the_loop("retention")

    async def test_ai_messages_appended_after_interrupt(self):
        with patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model") as mock:
            graph = InsightsAssistantGraph(self.team, self.user).compile_full_graph()
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": self.conversation.id,
                }
            }

            def interrupt_graph_1(_):
                raise NodeInterrupt("test")

            mock.return_value = RunnableLambda(interrupt_graph_1)
            await self._run_assistant_graph(graph, conversation=self.conversation)
            snapshot: StateSnapshot = await graph.aget_state(config)
            self.assertTrue(snapshot.next)
            self.assertEqual(snapshot.values["graph_status"], "interrupted")
            self.assertIsInstance(snapshot.values["messages"][-1], AssistantMessage)
            self.assertEqual(snapshot.values["messages"][-1].content, "test")

            def interrupt_graph_2(_):
                snapshot = async_to_sync(graph.aget_state)(config)
                self.assertEqual(snapshot.values["graph_status"], "resumed")
                raise NodeInterrupt("test")

            mock.return_value = RunnableLambda(interrupt_graph_2)
            await self._run_assistant_graph(graph, conversation=self.conversation)

    async def test_memory_collector_handles_interrupt_with_pending_tool_calls(self):
        """Test that memory collector correctly routes to tools when resuming from an interrupt with pending tool calls."""
        graph = (
            AssistantGraph(self.team, self.user)
            .add_memory_collector(AssistantNodeName.END)
            .add_memory_collector_tools()
            .compile()
        )

        config: RunnableConfig = {
            "configurable": {
                "thread_id": self.conversation.id,
            }
        }

        # Simulate an interrupt: Set state with AIMessage that has tool_calls but no corresponding ToolMessage
        await graph.aupdate_state(
            config,
            {
                "messages": [HumanMessage(content="We use a subscription model")],
                "memory_collection_messages": [
                    messages.AIMessage(
                        content="Analyzing business model",
                        tool_calls=[
                            {
                                "id": "tool_1",
                                "name": "core_memory_append",
                                "args": {"memory_content": "Company uses subscription pricing model"},
                            }
                        ],
                    )
                ],
            },
        )

        # Now resume - it should route to tools first to execute the pending tool call
        with patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model") as model_mock:
            # After tool execution, the model should return [Done]
            model_mock.return_value = RunnableLambda(lambda _: messages.AIMessage(content="[Done]"))

            output, _ = await self._run_assistant_graph(
                graph,
                conversation=self.conversation,
                is_new_conversation=False,
                message=None,
            )

        # Verify the memory was appended (tool was executed)
        await self.core_memory.arefresh_from_db()
        self.assertIn("Company uses subscription pricing model", self.core_memory.text)

    async def test_recursion_error_is_handled(self):
        class FakeStream:
            def __init__(self, *args, **kwargs):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise GraphRecursionError()

        with patch("langgraph.pregel.Pregel.astream", side_effect=FakeStream):
            output, _ = await self._run_assistant_graph(conversation=self.conversation)
            self.assertEqual(output[0][0], "message")
            self.assertEqual(cast(AssistantMessage, output[0][1]).content, "Hello")
            self.assertEqual(output[1][0], "message")
            self.assertIsInstance(output[1][1], FailureMessage)

    async def test_new_conversation_handles_serialized_conversation(self):
        from ee.hogai.graph.base import BaseAssistantNode

        class TestNode(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config):
                self.dispatcher.message(AssistantMessage(content="Hello"))
                return PartialAssistantState()

        test_node = TestNode(self.team, self.user)
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, test_node)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        output, _ = await self._run_assistant_graph(
            graph,
            conversation=self.conversation,
            is_new_conversation=True,
        )
        expected_output = [
            ("conversation", self.conversation),
        ]
        self.assertConversationEqual(output[:1], expected_output)

        output, _ = await self._run_assistant_graph(
            graph,
            conversation=self.conversation,
            is_new_conversation=False,
        )
        self.assertNotEqual(output[0][0], "conversation")

    async def test_async_stream(self):
        from ee.hogai.graph.base import BaseAssistantNode

        class TestNode(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config):
                self.dispatcher.message(AssistantMessage(content="bar"))
                return PartialAssistantState()

        test_node = TestNode(self.team, self.user)
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, test_node)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant.create(
            self.team, self.conversation, user=self.user, new_message=HumanMessage(content="foo")
        )
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
            ("message", AssistantMessage(content="bar")),
        ]
        actual_output = [
            event
            async for event in assistant.astream()
            if not (
                isinstance(event[1], AssistantGenerationStatusEvent)
                and event[1].type == AssistantGenerationStatusType.ACK
            )
        ]
        self.assertConversationEqual(actual_output, expected_output)

    async def test_async_stream_handles_exceptions(self):
        def node_handler(state):
            raise ValueError()

        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, node_handler)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant.create(
            self.team, self.conversation, user=self.user, new_message=HumanMessage(content="foo")
        )
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
            ("message", FailureMessage()),
        ]
        actual_output = []
        async for event in assistant.astream():
            actual_output.append(event)
        self.assertConversationEqual(actual_output, expected_output)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_trends_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
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
        res2 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res2])

        planner_mock.return_value = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "final_answer",
                            "args": {"query_kind": "trends", "plan": "Plan"},
                        }
                    ],
                )
            ]
        )
        query = AssistantTrendsQuery(series=[])
        generator_mock.return_value = RunnableLambda(lambda _: TrendsSchemaGeneratorOutput(query=query))

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
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
            ),
            (
                "update",
                AssistantUpdateEvent(
                    id="message_1",
                    tool_call_id="xyz",
                    content="Picking relevant events and properties",
                ),
            ),
            ("update", AssistantUpdateEvent(id="message_2", tool_call_id="xyz", content="Creating trends query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", {"tool_call_id": "xyz", "type": "tool"}),  # Don't check content as it's implementation detail
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(
            cast(HumanMessage, actual_output[1][1]).id, cast(VisualizationMessage, actual_output[5][1]).initiator
        )  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(
            cast(HumanMessage, actual_output[0][1]).id, cast(VisualizationMessage, actual_output[4][1]).initiator
        )

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(
            cast(HumanMessage, actual_output[0][1]).id, cast(VisualizationMessage, actual_output[4][1]).initiator
        )

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_funnel_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar", "query_kind": "funnel"},
                    }
                ],
            )
        )
        res2 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res2])

        planner_mock.return_value = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "final_answer",
                            "args": {"query_kind": "funnel", "plan": "Plan"},
                        }
                    ],
                )
            ]
        )
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview"),
                AssistantFunnelsEventsNode(event="$pageleave"),
            ]
        )
        generator_mock.return_value = RunnableLambda(lambda _: FunnelsSchemaGeneratorOutput(query=query))

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
                AssistantMessage(
                    content="",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={"query_description": "Foobar", "query_kind": "funnel"},
                        )
                    ],
                ),
            ),
            (
                "update",
                AssistantUpdateEvent(
                    id="message_1",
                    tool_call_id="xyz",
                    content="Picking relevant events and properties",
                ),
            ),
            ("update", AssistantUpdateEvent(id="message_2", tool_call_id="xyz", content="Creating funnel query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", {"tool_call_id": "xyz", "type": "tool"}),  # Don't check content as it's implementation detail
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(
            cast(HumanMessage, actual_output[1][1]).id, cast(VisualizationMessage, actual_output[5][1]).initiator
        )  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(
            cast(HumanMessage, actual_output[0][1]).id, cast(VisualizationMessage, actual_output[4][1]).initiator
        )

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(
            cast(HumanMessage, actual_output[0][1]).id, cast(VisualizationMessage, actual_output[4][1]).initiator
        )

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_retention_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        action = await Action.objects.acreate(team=self.team, name="Marius Tech Tips")

        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
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
        res2 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res2])

        planner_mock.return_value = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "final_answer",
                            "args": {"query_kind": "retention", "plan": "Plan"},
                        }
                    ],
                )
            ]
        )
        query = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity=AssistantRetentionEventsNode(name="$pageview"),
                returningEntity=AssistantRetentionActionsNode(name=action.name, id=action.id),
            )
        )
        generator_mock.return_value = RunnableLambda(lambda _: RetentionSchemaGeneratorOutput(query=query))

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
                AssistantMessage(
                    content="",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={"query_description": "Foobar", "query_kind": "retention"},
                        )
                    ],
                ),
            ),
            (
                "update",
                AssistantUpdateEvent(
                    id="message_1",
                    tool_call_id="xyz",
                    content="Picking relevant events and properties",
                ),
            ),
            ("update", AssistantUpdateEvent(id="message_2", tool_call_id="xyz", content="Creating retention query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", {"tool_call_id": "xyz", "type": "tool"}),  # Don't check content as it's implementation detail
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(
            cast(HumanMessage, actual_output[1][1]).id, cast(VisualizationMessage, actual_output[5][1]).initiator
        )  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(
            cast(HumanMessage, actual_output[0][1]).id, cast(VisualizationMessage, actual_output[4][1]).initiator
        )

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(
            cast(HumanMessage, actual_output[0][1]).id, cast(VisualizationMessage, actual_output[4][1]).initiator
        )

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_sql_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
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
        res2 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(content="The results indicate a great future for you.")
        )
        root_mock.side_effect = cycle([res1, res2])

        planner_mock.return_value = RunnableLambda(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "final_answer",
                        "args": {"query_kind": "sql", "plan": "Plan"},
                    }
                ],
                response_metadata={"id": "call_1"},
            )
        )
        query = AssistantHogQLQuery(query="SELECT 1")
        generator_mock.return_value = RunnableLambda(lambda _: query.model_dump())

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
                AssistantMessage(
                    content="",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={"query_description": "Foobar", "query_kind": "sql"},
                        )
                    ],
                ),
            ),
            (
                "update",
                AssistantUpdateEvent(
                    id="message_1",
                    tool_call_id="xyz",
                    content="Picking relevant events and properties",
                ),
            ),
            ("update", AssistantUpdateEvent(id="message_2", tool_call_id="xyz", content="Creating SQL query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", {"tool_call_id": "xyz", "type": "tool"}),  # Don't check content as it's implementation detail
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(
            cast(HumanMessage, actual_output[1][1]).id, cast(VisualizationMessage, actual_output[5][1]).initiator
        )  # viz message must have this id

    @patch("ee.hogai.graph.memory.nodes.MemoryOnboardingEnquiryNode._model")
    @patch("ee.hogai.graph.memory.nodes.MemoryInitializerNode._model")
    async def test_onboarding_flow_accepts_memory(self, model_mock, onboarding_enquiry_model_mock):
        await self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(
            lambda x: "Here's what I found on posthog.com: PostHog is a product analytics platform."
        )

        def mock_response(input_dict):
            input_str = str(input_dict)
            if "You are tasked with gathering information" in input_str:
                return "===What is your target market?"
            return "[Done]"

        onboarding_enquiry_model_mock.return_value = RunnableLambda(mock_response)

        # Create a graph with memory initialization flow
        graph = AssistantGraph(self.team, self.user).add_memory_onboarding(AssistantNodeName.END).compile()

        # First run - get the product description
        output, _ = await self._run_assistant_graph(graph, is_new_conversation=True, message=SLASH_COMMAND_INIT)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content=SLASH_COMMAND_INIT)),
            (
                "message",
                AssistantMessage(
                    content="Let me find information about your product to help me understand your project better. Looking at your event data, **`us.posthog.com`** may be relevant. This may take a minute…",
                ),
            ),
            (
                "message",
                # Kinda dirty but currently we determine the routing based on "Here's what I found" appearing in content
                AssistantMessage(
                    content="Here's what I found on posthog.com: PostHog is a product analytics platform."
                ),
            ),
            ("message", AssistantMessage(content=memory_prompts.SCRAPING_VERIFICATION_MESSAGE)),
        ]
        self.assertConversationEqual(output, expected_output)

        # Second run - accept the memory
        output, _ = await self._run_assistant_graph(
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
        core_memory = await CoreMemory.objects.aget(team=self.team)
        self.assertEqual(
            core_memory.initial_text,
            "Question: What does the company do?\nAnswer: Here's what I found on posthog.com: PostHog is a product analytics platform.\nQuestion: What is your target market?\nAnswer:",
        )

    @patch("ee.hogai.graph.memory.nodes.MemoryInitializerNode._model")
    @patch("ee.hogai.graph.memory.nodes.MemoryOnboardingEnquiryNode._model")
    async def test_onboarding_flow_rejects_memory(self, onboarding_enquiry_model_mock, model_mock):
        await self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(
            lambda _: "Here's what I found on posthog.com: PostHog is a product analytics platform."
        )
        onboarding_enquiry_model_mock.return_value = RunnableLambda(lambda _: "===What is your target market?")

        # Create a graph with memory initialization flow
        graph = AssistantGraph(self.team, self.user).add_memory_onboarding(AssistantNodeName.END).compile()

        # First run - get the product description
        output, _ = await self._run_assistant_graph(graph, is_new_conversation=True, message=SLASH_COMMAND_INIT)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content=SLASH_COMMAND_INIT)),
            (
                "message",
                AssistantMessage(
                    content="Let me find information about your product to help me understand your project better. Looking at your event data, **`us.posthog.com`** may be relevant. This may take a minute…",
                ),
            ),
            (
                "message",
                # Kinda dirty but currently we determine the routing based on "Here's what I found" appearing in content
                AssistantMessage(
                    content="Here's what I found on posthog.com: PostHog is a product analytics platform."
                ),
            ),
            ("message", AssistantMessage(content=memory_prompts.SCRAPING_VERIFICATION_MESSAGE)),
        ]
        self.assertConversationEqual(output, expected_output)

        # Second run - reject the memory
        output, _ = await self._run_assistant_graph(
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

        core_memory = await CoreMemory.objects.aget(team=self.team)
        self.assertEqual(core_memory.initial_text, "Question: What is your target market?\nAnswer:")

    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model")
    async def test_memory_collector_flow(self, model_mock):
        # Create a graph with just memory collection
        graph = (
            AssistantGraph(self.team, self.user)
            .add_memory_collector(AssistantNodeName.END)
            .add_memory_collector_tools()
            .compile()
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
        output, _ = await self._run_assistant_graph(
            graph,
            message="We use a subscription model",
            is_new_conversation=True,
        )
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="We use a subscription model")),
        ]
        self.assertConversationEqual(output, expected_output)

        # Verify memory was appended
        await self.core_memory.arefresh_from_db()
        self.assertIn("The product uses a subscription model.", self.core_memory.text)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_exits_infinite_loop_after_fourth_attempt(
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

        get_model_mock.return_value = FakeAnthropicRunnableLambdaWithTokenCounter(make_tool_call)
        planner_mock.return_value = RunnableLambda(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "final_answer",
                        "args": {"query_kind": "trends", "plan": "Plan"},
                    }
                ],
                response_metadata={"id": "call_1"},
            )
        )
        query = AssistantTrendsQuery(series=[])
        generator_mock.return_value = RunnableLambda(lambda _: TrendsSchemaGeneratorOutput(query=query))

        # Create a graph that only uses the root node
        graph = AssistantGraph(self.team, self.user).compile_full_graph()

        # Run the assistant and capture output
        output, _ = await self._run_assistant_graph(graph)

        # Verify the last message doesn't contain any tool calls and has our expected content
        last_message = cast(AssistantMessage, output[-1][1])
        self.assertNotIn("tool_calls", last_message, "The final message should not contain any tool calls")
        self.assertEqual(
            last_message.content,
            "No more tool calls after 4th attempt",
            "Final message should indicate no more tool calls",
        )

    async def test_conversation_is_locked_when_generating(self):
        graph = (
            AssistantGraph(self.team, self.user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root({"root": AssistantNodeName.ROOT, "end": AssistantNodeName.END})
            .compile()
        )
        self.assertEqual(self.conversation.status, Conversation.Status.IDLE)
        with patch("ee.hogai.graph.root.nodes.RootNode._get_model") as root_mock:

            def assert_lock_status(_):
                self.conversation.refresh_from_db()
                self.assertEqual(self.conversation.status, Conversation.Status.IN_PROGRESS)
                return messages.AIMessage(content="")

            root_mock.return_value = FakeAnthropicRunnableLambdaWithTokenCounter(assert_lock_status)
            await self._run_assistant_graph(graph)
            await self.conversation.arefresh_from_db()
            self.assertEqual(self.conversation.status, Conversation.Status.IDLE)

    async def test_conversation_saves_state_after_cancellation(self):
        graph = (
            AssistantGraph(self.team, self.user)
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

            root_mock.return_value = FakeAnthropicRunnableLambdaWithTokenCounter(assert_lock_status)
            await self._run_assistant_graph(graph)
            snapshot = await graph.aget_state({"configurable": {"thread_id": str(self.conversation.id)}})
            self.assertEqual(snapshot.next, (AssistantNodeName.ROOT_TOOLS,))
            self.assertEqual(snapshot.values["messages"][-1].content, "")
            root_tool_mock.assert_not_called()

        with patch("ee.hogai.graph.root.nodes.RootNode._get_model") as root_mock:
            # The graph must start from the root node despite being cancelled on the root tools node.
            root_mock.return_value = FakeAnthropicRunnableLambdaWithTokenCounter(
                lambda _: messages.AIMessage(content="Finished")
            )
            expected_output = [
                ("message", HumanMessage(content="Hello")),
                ("message", AssistantMessage(content="Finished")),
            ]
            actual_output, _ = await self._run_assistant_graph(graph)
            self.assertConversationEqual(actual_output, expected_output)

    @override_settings(INKEEP_API_KEY="test")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode._get_model")
    async def test_inkeep_docs_basic_search(self, inkeep_docs_model_mock, root_model_mock):
        """Test basic documentation search functionality using Inkeep."""
        graph = (
            AssistantGraph(self.team, self.user)
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

        root_model_mock.return_value = FakeChatAnthropic(
            responses=[
                messages.AIMessage(
                    content="", tool_calls=[{"name": "search", "id": "1", "args": {"kind": "docs", "query": "test"}}]
                )
            ]
        )
        inkeep_docs_model_mock.return_value = FakeChatOpenAI(
            responses=[messages.AIMessage(content="Here's what I found in the docs...")]
        )
        output, _ = await self._run_assistant_graph(graph, message="How do I use feature flags?")

        self.assertConversationEqual(
            output,
            [
                (
                    "message",
                    HumanMessage(
                        content="How do I use feature flags?",
                        id="d93b3d57-2ff3-4c63-8635-8349955b16f0",
                        parent_tool_call_id=None,
                        type="human",
                        ui_context=None,
                    ),
                ),
                (
                    "message",
                    AssistantMessage(
                        content="",
                        id="ea1f4faf-85b4-4d98-b044-842b7092ba5d",
                        meta=None,
                        parent_tool_call_id=None,
                        tool_calls=[
                            AssistantToolCall(
                                args={"kind": "docs", "query": "test"}, id="1", name="search", type="tool_call"
                            )
                        ],
                        type="ai",
                    ),
                ),
                (
                    "update",
                    AssistantUpdateEvent(id="message_2", tool_call_id="1", content="Checking PostHog documentation..."),
                ),
                (
                    "message",
                    AssistantToolCallMessage(
                        content="Checking PostHog documentation...",
                        id="00149847-0bcd-4b7c-a514-bab176312ae8",
                        parent_tool_call_id=None,
                        tool_call_id="1",
                        type="tool",
                        ui_payload=None,
                    ),
                ),
                (
                    "message",
                    AssistantMessage(content="Here's what I found in the docs...", id=str(uuid4())),
                ),
            ],
        )

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.graph.QueryExecutorNode")
    async def test_insights_tool_mode_flow(
        self, query_executor_mock, planner_mock, generator_mock, title_generator_mock
    ):
        """Test that the insights tool mode works correctly."""
        query = AssistantTrendsQuery(series=[])
        tool_call_id = str(uuid4())
        tool_call_state = AssistantState(
            root_tool_call_id=tool_call_id,
            root_tool_insight_plan="Foobar",
            root_tool_insight_type="trends",
            messages=[],
        )

        planner_mock.return_value = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "final_answer",
                            "args": {"query_kind": "trends", "plan": "Plan"},
                        }
                    ],
                )
            ]
        )
        generator_mock.return_value = RunnableLambda(lambda _: TrendsSchemaGeneratorOutput(query=query))

        class QueryExecutorNodeMock(BaseAssistantNode):
            def __init__(self, team, user):
                super().__init__(team, user)

            @property
            def node_name(self):
                return AssistantNodeName.QUERY_EXECUTOR

            async def arun(self, state, config):
                return PartialAssistantState(
                    messages=[
                        AssistantToolCallMessage(
                            content="The results indicate a great future for you.", tool_call_id=tool_call_id
                        )
                    ]
                )

        query_executor_mock.return_value = QueryExecutorNodeMock(self.team, self.user)

        # Run in insights tool mode
        output, _ = await self._run_assistant_graph(
            conversation=self.conversation,
            is_new_conversation=False,
            message=None,
            mode=AssistantMode.INSIGHTS_TOOL,
            tool_call_partial_state=tool_call_state,
        )

        expected_output = [
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            (
                "message",
                AssistantToolCallMessage(
                    content="The results indicate a great future for you.", tool_call_id=tool_call_id
                ),
            ),
        ]
        self.assertConversationEqual(output, expected_output)

    @patch("ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model")
    async def test_conversation_metadata_updated(self, title_generator_model_mock):
        """Test that metadata (title, created_at, updated_at) is generated and set for a new conversation."""
        # Create a test graph with only the title generator node
        graph = AssistantGraph(self.team, self.user).add_title_generator().compile()
        initial_updated_at = self.conversation.updated_at
        initial_created_at = self.conversation.created_at

        self.assertIsNone(self.conversation.title)

        # Mock the title generator to return "Generated Conversation Title"
        title_generator_model_mock.return_value = FakeChatOpenAI(
            responses=[messages.AIMessage(content="Generated Conversation Title")]
        )

        # Run the assistant
        await self._run_assistant_graph(
            graph,
            message="This is the first message in the conversation",
            is_new_conversation=True,
        )

        # Assert the conversation doesn't have a title yet
        await self.conversation.arefresh_from_db()
        # Verify the title has been set
        self.assertEqual(self.conversation.title, "Generated Conversation Title")
        assert self.conversation.updated_at is not None
        assert initial_updated_at is not None
        self.assertGreater(self.conversation.updated_at, initial_updated_at)
        self.assertEqual(self.conversation.created_at, initial_created_at)

    async def test_merges_messages_with_same_id(self):
        """Test that messages with the same ID are merged into one."""
        from ee.hogai.graph.base import BaseAssistantNode

        message_ids = [str(uuid4()), str(uuid4())]

        # Create a simple graph that will return messages with the same ID but different content
        first_content = "First version of message"
        updated_content = "Updated version of message"

        class MessageUpdatingNode(BaseAssistantNode):
            def __init__(self, team, user):
                super().__init__(team, user)
                self.call_count = 0

            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config):
                self.call_count += 1
                content = first_content if self.call_count == 1 else updated_content
                msg = AssistantMessage(id=message_ids[self.call_count - 1], content=content)
                return PartialAssistantState(messages=[msg])

        updater = MessageUpdatingNode(self.team, self.user)
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, updater)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        config = RunnableConfig(configurable={"thread_id": self.conversation.id})

        # First run should add the message with initial content
        output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
        self.assertEqual(len(output), 2)  # Human message + AI message
        self.assertEqual(cast(AssistantMessage, output[1][1]).id, message_ids[0])
        self.assertEqual(cast(AssistantMessage, output[1][1]).content, first_content)

        # Second run should update the message with new content
        output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
        self.assertEqual(len(output), 2)  # Human message + AI message
        self.assertEqual(cast(AssistantMessage, output[1][1]).id, message_ids[1])
        self.assertEqual(cast(AssistantMessage, output[1][1]).content, updated_content)

        # Verify the message was actually replaced, not duplicated
        snapshot = await graph.aget_state(config)
        messages = snapshot.values["messages"]

        # Count messages with our test ID
        messages_with_id = [msg for msg in messages if msg.id == message_ids[1]]
        self.assertEqual(len(messages_with_id), 1, "There should be exactly one message with the test ID")
        self.assertEqual(
            messages_with_id[0].content,
            updated_content,
            "The merged message should have the content of the last message",
        )

    async def test_assistant_filters_messages_correctly(self):
        """Test that the Assistant class correctly filters messages based on should_output_assistant_message."""
        from ee.hogai.graph.base import BaseAssistantNode

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
            # Should be output (tool call messages are not filtered by ui_payload)
            (AssistantToolCallMessage(content="Tool result", tool_call_id="456", id="4", ui_payload=None), True),
        ]

        for test_message, expected_in_output in output_messages:
            # Create a simple graph that produces different message types to test filtering
            class MessageFilteringNode(BaseAssistantNode):
                def __init__(self, team, user, message_to_return):
                    super().__init__(team, user)
                    self.message_to_return = message_to_return

                @property
                def node_name(self):
                    return AssistantNodeName.ROOT

                async def arun(self, state, config):
                    self.dispatcher.message(self.message_to_return)
                    return PartialAssistantState()

            # Create a graph with our test node
            node = MessageFilteringNode(self.team, self.user, test_message)
            graph = (
                AssistantGraph(self.team, self.user)
                .add_node(AssistantNodeName.ROOT, node)
                .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                .compile()
            )

            # Run the assistant and capture output
            output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
            expected_output: list = [
                ("message", HumanMessage(content="Hello")),
            ]

            if expected_in_output:
                expected_output.append(("message", test_message))

            self.assertConversationEqual(output, expected_output)

    async def test_ui_context_persists_through_conversation_retrieval(self):
        """Test that ui_context persists when retrieving conversation state across multiple runs."""

        # Create a simple graph that just returns the initial state
        def return_initial_state(state):
            return {"messages": [AssistantMessage(content="Response from assistant")]}

        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, return_initial_state)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )

        # Test ui_context with multiple fields
        ui_context = MaxUIContext(
            dashboards=[
                MaxDashboardContext(
                    id=1,
                    filters=DashboardFilter(),
                    insights=[MaxInsightContext(id="1", query=TrendsQuery(series=[]))],
                )
            ],
            insights=[MaxInsightContext(id="2", query=TrendsQuery(series=[]))],
        )

        # First run: Create assistant with ui_context
        output1, assistant1 = await self._run_assistant_graph(
            test_graph=graph,
            message="First message",
            conversation=self.conversation,
            ui_context=ui_context,
        )

        ui_context_2 = MaxUIContext(insights=[MaxInsightContext(id="3", query=TrendsQuery(series=[]))])

        # Second run: Create another assistant with the same conversation (simulating retrieval)
        output2, assistant2 = await self._run_assistant_graph(
            test_graph=graph,
            message="Second message",
            conversation=self.conversation,
            ui_context=ui_context_2,  # Different ui_context
        )

        # Get the final state
        config2 = assistant2._get_config()
        state2 = await assistant2._graph.aget_state(config2)
        stored_messages2 = state2.values["messages"]

        # Find all human messages in the final stored messages
        human_messages = [msg for msg in stored_messages2 if isinstance(msg, HumanMessage)]
        self.assertEqual(len(human_messages), 2, "Should have exactly two human messages")

        first_message = human_messages[0]
        self.assertEqual(first_message.ui_context, ui_context)

        # Check second message has new ui_context
        second_message = human_messages[1]
        self.assertEqual(second_message.ui_context, ui_context_2)

    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.arun")
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.rag.nodes.InsightRagContextNode.run")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    async def test_create_and_query_insight_contextual_tool(
        self, root_mock, rag_mock, planner_mock, generator_mock, query_executor_mock
    ):
        def root_side_effect(msgs: list[BaseMessage]):
            last_message = msgs[-1]

            if (
                isinstance(last_message.content, list)
                and isinstance(last_message.content[-1], dict)
                and last_message.content[-1]["type"] == "tool_result"
            ):
                return RunnableLambda(lambda _: messages.AIMessage(content="Everything is fine"))

            return messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "edit_current_insight",
                        "args": {"query_description": "Foobar", "query_kind": "trends"},
                    }
                ],
            )

        root_mock.return_value = FakeAnthropicRunnableLambdaWithTokenCounter(root_side_effect)
        rag_mock.return_value = PartialAssistantState(
            rag_context="",
        )

        planner_mock.return_value = FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "final_answer",
                            "args": {"query_kind": "trends", "plan": "Plan"},
                        }
                    ],
                )
            ]
        )
        query = AssistantTrendsQuery(series=[])
        generator_mock.return_value = RunnableLambda(lambda _: TrendsSchemaGeneratorOutput(query=query))

        query_executor_mock.return_value = PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content="The results indicate a great future for you.", tool_call_id="xyz")
            ],
        )

        output, assistant = await self._run_assistant_graph(
            test_graph=AssistantGraph(self.team, self.user)
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
            message="Hello",
            mode=AssistantMode.ASSISTANT,
            contextual_tools={"edit_current_insight": {"current_query": "query"}},
        )

        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            (
                "message",
                AssistantMessage(
                    content="",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="edit_current_insight",
                            args={"query_description": "Foobar", "query_kind": "trends"},
                        )
                    ],
                ),
            ),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            (
                "message",
                {
                    "tool_call_id": "xyz",
                    "type": "tool",
                    "ui_payload": {"edit_current_insight": query.model_dump(exclude_none=True)},
                },  # Don't check content as it's implementation detail
            ),
            ("message", AssistantMessage(content="Everything is fine")),
        ]
        self.assertConversationEqual(output, expected_output)

        snapshot = await assistant._graph.aget_state(assistant._get_config())
        state = AssistantState.model_validate(snapshot.values)
        expected_state_messages = [
            ContextMessage(
                content="<system_reminder>\nContextual tools that are available to you on this page are:\n<edit_current_insight>\nThe user is currently editing an insight (aka query). Here is that insight's current definition, which can be edited using the `edit_current_insight` tool:\n\n```json\nquery\n```\n\nIMPORTANT: DO NOT REMOVE ANY FIELDS FROM THE CURRENT INSIGHT DEFINITION. DO NOT CHANGE ANY OTHER FIELDS THAN THE ONES THE USER ASKED FOR. KEEP THE REST AS IS.\n</edit_current_insight>\nIMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.\n</system_reminder>"
            ),
            HumanMessage(content="Hello"),
            AssistantMessage(
                content="",
                tool_calls=[
                    AssistantToolCall(
                        id="xyz",
                        name="edit_current_insight",
                        args={"query_description": "Foobar", "query_kind": "trends"},
                    )
                ],
            ),
            VisualizationMessage(query="Foobar", answer=query, plan="Plan"),
            AssistantToolCallMessage(
                content="The results indicate a great future for you.",
                tool_call_id="xyz",
                ui_payload={"edit_current_insight": query.model_dump(exclude_none=True)},
            ),
            AssistantMessage(content="Everything is fine"),
        ]
        state = cast(AssistantState, state)
        self.assertStateMessagesEqual(cast(list[Any], state.messages), expected_state_messages)

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    async def test_continue_generation_without_new_message(self, root_mock):
        """Test that the assistant can continue generation without a new message (askMax(null) scenario)"""
        root_mock.return_value = FakeChatOpenAI(
            responses=[messages.AIMessage(content="Based on the previous analysis, I can provide insights.")]
        )

        graph = (
            AssistantGraph(self.team, self.user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root({"root": AssistantNodeName.ROOT, "end": AssistantNodeName.END})
            .compile()
        )

        # First, set up the conversation with existing messages and tool call result
        config: RunnableConfig = {"configurable": {"thread_id": self.conversation.id}}
        await graph.aupdate_state(
            config,
            {
                "messages": [
                    HumanMessage(content="Analyze trends"),
                    AssistantMessage(
                        content="Let me analyze",
                        tool_calls=[
                            AssistantToolCall(
                                id="tool-1",
                                name="create_and_query_insight",
                                args={"query_description": "test"},
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        content="Tool execution complete",
                        tool_call_id="tool-1",
                    ),
                ]
            },
        )

        # Continue without a new user message (simulates askMax(null))
        output, _ = await self._run_assistant_graph(
            test_graph=graph,
            conversation=self.conversation,
            is_new_conversation=False,
            message=None,  # This simulates askMax(null)
            mode=AssistantMode.ASSISTANT,
        )

        # Verify the assistant continued generation with the expected message
        assistant_messages = [msg for _, msg in output if isinstance(msg, AssistantMessage)]
        self.assertTrue(len(assistant_messages) > 0, "Expected at least one assistant message")
        # The root node should have generated the continuation message we mocked
        final_message = assistant_messages[-1]
        self.assertEqual(
            final_message.content,
            "Based on the previous analysis, I can provide insights.",
            "Expected the root node to generate continuation message",
        )

    # Tests for ainvoke method
    async def test_ainvoke_basic_functionality(self):
        """Test ainvoke returns all messages at once without streaming."""
        from ee.hogai.graph.base import BaseAssistantNode

        class TestNode(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config):
                self.dispatcher.message(AssistantMessage(content="Response"))
                return PartialAssistantState()

        test_node = TestNode(self.team, self.user)
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, test_node)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )

        assistant = Assistant.create(
            self.team,
            self.conversation,
            user=self.user,
            new_message=HumanMessage(content="Test"),
        )
        assistant._graph = graph

        result = await assistant.ainvoke()

        # Should return list of tuples with correct structure
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        item = result[0]
        # Check structure of each result
        self.assertIsInstance(item, tuple)
        self.assertEqual(len(item), 2)
        self.assertEqual(item[0], AssistantEventType.MESSAGE)
        self.assertIsInstance(item[1], AssistantMessage)
        self.assertEqual(cast(AssistantMessage, item[1]).content, "Response")

    async def test_process_value_update_returns_none(self):
        """Test that _aprocess_value_update returns None for basic state updates (ACKs are now handled by reducer)."""

        assistant = Assistant.create(
            self.team, self.conversation, new_message=HumanMessage(content="Hello"), user=self.user
        )

        # Create a value update tuple that doesn't match special nodes
        update = cast(
            GraphValueUpdateTuple,
            (
                AssistantNodeName.ROOT,
                {"root": {"messages": []}},  # Empty update that doesn't match visualization or verbose nodes
            ),
        )

        # Process the update
        result = await assistant._aprocess_value_update(update)

        # Should return None (ACK events are now generated by the reducer)
        self.assertIsNone(result)

    def test_billing_context_in_config(self):
        billing_context = MaxBillingContext(
            has_active_subscription=True,
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            settings=MaxBillingContextSettings(active_destinations=2.0, autocapture_on=True),
            products=[
                MaxProductInfo(
                    name="Product Analytics",
                    description="Track user behavior",
                    current_usage=1000000.0,
                    has_exceeded_limit=False,
                    is_used=True,
                    percentage_usage=85.0,
                    type="product_analytics",
                    addons=[
                        MaxAddonInfo(
                            name="Data Pipeline",
                            description="Advanced data pipeline features",
                            current_usage=100.0,
                            has_exceeded_limit=False,
                            is_used=True,
                            type="data_pipeline",
                        )
                    ],
                )
            ],
        )
        assistant = Assistant.create(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
            billing_context=billing_context,
        )

        config = assistant._get_config()
        self.assertEqual(config.get("configurable", {}).get("billing_context"), billing_context)

    @patch(
        "ee.hogai.graph.conversation_summarizer.nodes.AnthropicConversationSummarizer.summarize",
        new=AsyncMock(return_value="Summary"),
    )
    @patch("ee.hogai.graph.root.compaction_manager.AnthropicConversationCompactionManager.should_compact_conversation")
    @patch("ee.hogai.graph.root.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    async def test_compacting_conversation_on_the_second_turn(self, mock_model, mock_tool, mock_should_compact):
        mock_model.side_effect = cycle(  # Changed from return_value to side_effect
            [
                FakeChatAnthropic(
                    responses=[
                        messages.AIMessage(
                            content=[{"text": "Let me think about that", "type": "text"}],
                            tool_calls=[{"id": "1", "name": "read_taxonomy", "args": {"query": {"kind": "events"}}}],
                        )
                    ]
                ),
                FakeChatAnthropic(
                    responses=[
                        messages.AIMessage(
                            content=[{"text": "After summary", "type": "text"}],
                        )
                    ]
                ),
            ]
        )
        mock_tool.return_value = ("Event list" * 128000, None)
        mock_should_compact.side_effect = cycle([False, True])  # Also changed this

        graph = (
            AssistantGraph(self.team, self.user)
            .add_root(
                path_map={
                    "insights": AssistantNodeName.END,
                    "search_documentation": AssistantNodeName.END,
                    "root": AssistantNodeName.ROOT,
                    "end": AssistantNodeName.END,
                    "insights_search": AssistantNodeName.END,
                    "session_summarization": AssistantNodeName.END,
                    "create_dashboard": AssistantNodeName.END,
                }
            )
            .add_memory_onboarding()
            .compile()
        )

        expected_output = [
            ("message", HumanMessage(content="First")),
            (
                "message",
                AssistantMessage(
                    content="Let me think about that",
                    tool_calls=[{"id": "1", "name": "read_taxonomy", "args": {"query": {"kind": "events"}}}],
                ),
            ),
            ("message", AssistantToolCallMessage(tool_call_id="1", content="Event list" * 128000)),
            ("message", HumanMessage(content="First")),  # Should copy this message
            ("message", AssistantMessage(content="After summary")),
        ]

        output, _ = await self._run_assistant_graph(graph, message="First", conversation=self.conversation)
        self.assertConversationEqual(output, expected_output)

        snapshot = await graph.aget_state({"configurable": {"thread_id": str(self.conversation.id)}})
        state = AssistantState.model_validate(snapshot.values)
        # should be equal to the copied human message
        new_human_message = cast(HumanMessage, output[3][1])
        self.assertEqual(state.start_id, new_human_message.id)
        # should be equal to the summary message, minus reasoning message
        self.assertEqual(state.root_conversation_start_id, state.messages[3].id)
