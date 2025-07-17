from itertools import cycle
from typing import Any, Literal, Optional, cast
from unittest.mock import patch
from uuid import uuid4

from asgiref.sync import async_to_sync
from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.models import EmbeddingsResult, EmbeddingsUsage
from azure.core.credentials import AzureKeyCredential
from django.test import override_settings
from langchain_core import messages
from langchain_core.prompts.chat import ChatPromptValue
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.errors import GraphRecursionError, NodeInterrupt
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.funnels.nodes import FunnelsSchemaGeneratorOutput
from ee.hogai.graph.memory import prompts as memory_prompts, prompts as onboarding_prompts
from ee.hogai.graph.retention.nodes import RetentionSchemaGeneratorOutput
from ee.hogai.graph.trends.nodes import TrendsSchemaGeneratorOutput
from ee.hogai.tool import search_documentation
from ee.hogai.utils.tests import FakeChatOpenAI, FakeRunnableLambdaWithTokenCounter
from ee.hogai.utils.types import (
    AssistantMode,
    AssistantNodeName,
    AssistantOutput,
    AssistantState,
    PartialAssistantState,
)
from ee.models.assistant import Conversation, CoreMemory
from posthog.models import Action
from posthog.schema import (
    AssistantEventType,
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
    DashboardFilter,
    FailureMessage,
    HumanMessage,
    MaxDashboardContext,
    MaxInsightContext,
    MaxUIContext,
    ReasoningMessage,
    TrendsQuery,
    VisualizationMessage,
)
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event, _create_person

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

    async def _run_assistant_graph(
        self,
        test_graph: Optional[CompiledStateGraph] = None,
        message: Optional[str] = "Hello",
        conversation: Optional[Conversation] = None,
        tool_call_partial_state: Optional[AssistantState | PartialAssistantState] = None,
        is_new_conversation: bool = False,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        contextual_tools: Optional[dict[str, Any]] = None,
        ui_context: Optional[MaxUIContext] = None,
    ) -> tuple[list[tuple[str, Any]], Assistant]:
        # Create assistant instance with our test graph
        assistant = Assistant(
            self.team,
            conversation or self.conversation,
            new_message=HumanMessage(content=message or "Hello", ui_context=ui_context),
            user=self.user,
            is_new_conversation=is_new_conversation,
            tool_call_partial_state=tool_call_partial_state,
            mode=mode,
            contextual_tools=contextual_tools,
        )
        if test_graph:
            assistant._graph = test_graph
        # Capture and parse output of assistant.astream()
        output: list[AssistantOutput] = []
        async for event in assistant.astream():
            output.append(event)
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
            elif output_msg_type == AssistantEventType.MESSAGE and expected_msg_type == AssistantEventType.MESSAGE:
                msg_dict = (
                    expected_msg.model_dump(exclude_none=True) if isinstance(expected_msg, BaseModel) else expected_msg
                )
                self.assertDictContainsSubset(
                    msg_dict,
                    cast(BaseModel, output_msg).model_dump(exclude_none=True),
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
            msg_dict = message.model_dump(exclude_none=True) if isinstance(message, BaseModel) else message
            self.assertDictContainsSubset(expected_msg_dict, msg_dict, f"Message content mismatch at index {i}")

    @patch(
        "ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model",
        return_value=FakeChatOpenAI(
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
        ),
    )
    @patch(
        "ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run",
        return_value=PartialAssistantState(
            messages=[AssistantMessage(content="Foobar")],
        ),
    )
    async def test_reasoning_messages_added(self, _mock_query_executor_run, _mock_query_planner_run):
        output, _ = await self._run_assistant_graph(
            InsightsAssistantGraph(self.team, self.user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.QUERY_PLANNER)
            .add_query_planner(
                {
                    "continue": AssistantNodeName.QUERY_PLANNER,
                    "trends": AssistantNodeName.END,
                    "funnel": AssistantNodeName.END,
                    "retention": AssistantNodeName.END,
                    "sql": AssistantNodeName.END,
                    "end": AssistantNodeName.END,
                }
            )
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
                    "content": "Picking relevant events and properties",
                    "substeps": [],
                },
            ),
        ]
        self.assertConversationEqual(output, expected_output)

    @patch(
        "ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model",
        return_value=FakeChatOpenAI(
            responses=[
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "retrieve_entity_properties",
                            "args": {"entity": "session"},
                        }
                    ],
                ),
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_2",
                            "name": "retrieve_event_properties",
                            "args": {"event_name": "$pageview"},
                        }
                    ],
                ),
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_3",
                            "name": "retrieve_event_property_values",
                            "args": {"event_name": "purchase", "property_name": "currency"},
                        }
                    ],
                ),
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_4",
                            "name": "retrieve_entity_property_values",
                            "args": {"entity": "person", "property_name": "country_of_birth"},
                        }
                    ],
                ),
                messages.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_6",
                            "name": "final_answer",
                            "args": {"query_kind": "trends", "plan": "Plan"},
                        }
                    ],
                ),
            ]
        ),
    )
    async def test_reasoning_messages_with_substeps_added(self, _mock_query_planner_run):
        output, _ = await self._run_assistant_graph(
            InsightsAssistantGraph(self.team, self.user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.QUERY_PLANNER)
            .add_query_planner(
                {
                    "continue": AssistantNodeName.QUERY_PLANNER,
                    "trends": AssistantNodeName.END,
                    "funnel": AssistantNodeName.END,
                    "retention": AssistantNodeName.END,
                    "sql": AssistantNodeName.END,
                    "end": AssistantNodeName.END,
                }
            )
            .compile(),
            conversation=self.conversation,
            tool_call_partial_state=PartialAssistantState(root_tool_call_id="foo"),
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
                    "content": "Picking relevant events and properties",
                    "substeps": [],
                },
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",
                    "substeps": [
                        "Exploring session properties",
                    ],
                },
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",
                    "substeps": [
                        "Exploring session properties",
                        "Exploring `$pageview` event's properties",
                    ],
                },
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",
                    "substeps": [
                        "Exploring session properties",
                        "Exploring `$pageview` event's properties",
                        "Analyzing `purchase` event's property `currency`",
                    ],
                },
            ),
            (
                "message",
                {
                    "type": "ai/reasoning",
                    "content": "Picking relevant events and properties",
                    "substeps": [
                        "Exploring session properties",
                        "Exploring `$pageview` event's properties",
                        "Analyzing `purchase` event's property `currency`",
                        "Analyzing person property `country_of_birth`",
                    ],
                },
            ),
        ]
        self.assertConversationEqual(output, expected_output)

    async def test_action_reasoning_messages_added(self):
        action = await Action.objects.acreate(team=self.team, name="Marius Tech Tips")

        with patch(
            "ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    messages.AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "retrieve_action_properties",
                                "args": {"action_id": action.id},
                            }
                        ],
                    ),
                    messages.AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_2",
                                "name": "retrieve_action_property_values",
                                "args": {"action_id": action.id, "property_name": "video_name"},
                            }
                        ],
                    ),
                    messages.AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_3",
                                "name": "final_answer",
                                "args": {"query_kind": "trends", "plan": "Plan"},
                            }
                        ],
                    ),
                ]
            ),
        ):
            output, _ = await self._run_assistant_graph(
                InsightsAssistantGraph(self.team, self.user)
                .add_edge(AssistantNodeName.START, AssistantNodeName.QUERY_PLANNER)
                .add_query_planner(
                    {
                        "continue": AssistantNodeName.QUERY_PLANNER,
                        "trends": AssistantNodeName.END,
                        "funnel": AssistantNodeName.END,
                        "retention": AssistantNodeName.END,
                        "sql": AssistantNodeName.END,
                        "end": AssistantNodeName.END,
                    }
                )
                .compile(),
                tool_call_partial_state=PartialAssistantState(root_tool_call_id="foo"),
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
                        "content": "Picking relevant events and properties",
                        "substeps": [],
                    },
                ),
                (
                    "message",
                    {
                        "type": "ai/reasoning",
                        "content": "Picking relevant events and properties",
                        "substeps": [
                            "Exploring `Marius Tech Tips` action properties",
                        ],
                    },
                ),
                (
                    "message",
                    {
                        "type": "ai/reasoning",
                        "content": "Picking relevant events and properties",
                        "substeps": [
                            "Exploring `Marius Tech Tips` action properties",
                            "Analyzing `video_name` action property of `Marius Tech Tips`",
                        ],
                    },
                ),
            ]
            self.assertConversationEqual(output, expected_output)

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
                ("message", AssistantMessage(content="Okay")),
                ("message", ReasoningMessage(content="Coming up with an insight")),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
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

            def interrupt_graph(_):
                raise NodeInterrupt("test")

            mock.return_value = RunnableLambda(interrupt_graph)
            await self._run_assistant_graph(graph, conversation=self.conversation)
            snapshot: StateSnapshot = await graph.aget_state(config)
            self.assertTrue(snapshot.next)
            self.assertEqual(snapshot.values["graph_status"], "interrupted")
            self.assertIsInstance(snapshot.values["messages"][-1], AssistantMessage)
            self.assertEqual(snapshot.values["messages"][-1].content, "test")

            def interrupt_graph(_):
                snapshot = async_to_sync(graph.aget_state)(config)
                self.assertEqual(snapshot.values["graph_status"], "resumed")
                raise NodeInterrupt("test")

            mock.return_value = RunnableLambda(interrupt_graph)
            await self._run_assistant_graph(graph, conversation=self.conversation)

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
            self.assertEqual(output[0][1].content, "Hello")
            self.assertEqual(output[1][0], "message")
            self.assertIsInstance(output[1][1], FailureMessage)

    async def test_new_conversation_handles_serialized_conversation(self):
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, lambda _: {"messages": [AssistantMessage(content="Hello")]})
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
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, lambda _: {"messages": [AssistantMessage(content="bar")]})
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        assistant = Assistant(self.team, self.conversation, user=self.user, new_message=HumanMessage(content="foo"))
        assistant._graph = graph

        expected_output = [
            ("message", HumanMessage(content="foo")),
            ("message", AssistantMessage(content="bar")),
        ]
        actual_output = [message async for message in assistant.astream()]
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
        assistant = Assistant(self.team, self.conversation, user=self.user, new_message=HumanMessage(content="foo"))
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
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating trends query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[5][1].initiator)  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[4][1].initiator)

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[4][1].initiator)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_funnel_flow(
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
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating funnel query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[5][1].initiator)  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[4][1].initiator)

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[4][1].initiator)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_retention_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
        action = await Action.objects.acreate(team=self.team, name="Marius Tech Tips")

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
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating retention query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[5][1].initiator)  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[4][1].initiator)

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[4][1].initiator)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    @patch("ee.hogai.graph.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]"))
    async def test_full_sql_flow(
        self, memory_collector_mock, root_mock, planner_mock, generator_mock, title_generator_mock
    ):
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
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating SQL query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[5][1].initiator)  # viz message must have this id

    @patch("ee.hogai.graph.memory.nodes.MemoryOnboardingEnquiryNode._model")
    @patch("ee.hogai.graph.memory.nodes.MemoryInitializerNode._model")
    async def test_onboarding_flow_accepts_memory(self, model_mock, onboarding_enquiry_model_mock):
        await self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(lambda x: "PostHog is a product analytics platform.")

        def mock_response(input_dict):
            input_str = str(input_dict)
            if "You are tasked with gathering information" in input_str:
                return "===What is your target market?"
            return "[Done]"

        onboarding_enquiry_model_mock.return_value = RunnableLambda(mock_response)

        # Create a graph with memory initialization flow
        graph = (
            AssistantGraph(self.team, self.user)
            .add_memory_onboarding(AssistantNodeName.END, AssistantNodeName.END)
            .compile()
        )

        # First run - get the product description
        output, _ = await self._run_assistant_graph(
            graph, is_new_conversation=True, message=onboarding_prompts.ONBOARDING_INITIAL_MESSAGE
        )
        expected_output = [
            ("conversation", self.conversation),
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
            "Question: What does the company do?\nAnswer: PostHog is a product analytics platform.\nQuestion: What is your target market?\nAnswer:",
        )

    @patch("ee.hogai.graph.memory.nodes.MemoryInitializerNode._model")
    @patch("ee.hogai.graph.memory.nodes.MemoryOnboardingEnquiryNode._model")
    async def test_onboarding_flow_rejects_memory(self, onboarding_enquiry_model_mock, model_mock):
        await self._set_up_onboarding_tests()

        # Mock the memory initializer to return a product description
        model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")
        onboarding_enquiry_model_mock.return_value = RunnableLambda(lambda _: "===What is your target market?")

        # Create a graph with memory initialization flow
        graph = (
            AssistantGraph(self.team, self.user)
            .add_memory_onboarding(AssistantNodeName.END, AssistantNodeName.END)
            .compile()
        )

        # First run - get the product description
        output, _ = await self._run_assistant_graph(
            graph, is_new_conversation=True, message=onboarding_prompts.ONBOARDING_INITIAL_MESSAGE
        )
        expected_output = [
            ("conversation", self.conversation),
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

        get_model_mock.return_value = FakeRunnableLambdaWithTokenCounter(make_tool_call)
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
        last_message = output[-1][1]
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

            root_mock.return_value = FakeRunnableLambdaWithTokenCounter(assert_lock_status)
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

            root_mock.return_value = FakeRunnableLambdaWithTokenCounter(assert_lock_status)
            await self._run_assistant_graph(graph)
            snapshot = await graph.aget_state({"configurable": {"thread_id": str(self.conversation.id)}})
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
        output, _ = await self._run_assistant_graph(graph, message="How do I use feature flags?")

        self.assertConversationEqual(
            output,
            [
                ("message", HumanMessage(content="How do I use feature flags?")),
                ("message", ReasoningMessage(content="Checking PostHog docs")),
                ("message", AssistantMessage(content="Here's what I found in the docs...")),
            ],
        )

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run")
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
        output, _ = await self._run_assistant_graph(
            conversation=self.conversation,
            is_new_conversation=False,
            message=None,
            mode=AssistantMode.INSIGHTS_TOOL,
            tool_call_partial_state=tool_call_state,
        )

        expected_output = [
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
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, updater)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )
        config = {"configurable": {"thread_id": self.conversation.id}}

        # First run should add the message with initial content
        output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
        self.assertEqual(len(output), 2)  # Human message + AI message
        self.assertEqual(output[1][1].id, message_id)
        self.assertEqual(output[1][1].content, first_content)

        # Second run should update the message with new content
        output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
        self.assertEqual(len(output), 2)  # Human message + AI message
        self.assertEqual(output[1][1].id, message_id)
        self.assertEqual(output[1][1].content, updated_content)

        # Verify the message was actually replaced, not duplicated
        snapshot = await graph.aget_state(config)
        messages = snapshot.values["messages"]

        # Count messages with our test ID
        messages_with_id = [msg for msg in messages if msg.id == message_id]
        self.assertEqual(len(messages_with_id), 1, "There should be exactly one message with the test ID")
        self.assertEqual(
            messages_with_id[0].content,
            updated_content,
            "The merged message should have the content of the last message",
        )

    async def test_assistant_filters_messages_correctly(self):
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
                AssistantGraph(self.team, self.user)
                .add_node(AssistantNodeName.ROOT, MessageFilteringNode(test_message))
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
                    id="1",
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

    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run")
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.graph.rag.nodes.InsightRagContextNode.run")
    @patch("ee.hogai.graph.root.nodes.RootNode._get_model")
    async def test_create_and_query_insight_contextual_tool(
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
            message=None,
            mode=AssistantMode.ASSISTANT,
            contextual_tools={"create_and_query_insight": {"current_query": "query"}},
        )

        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
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

        snapshot = await assistant._graph.aget_state(assistant._get_config())
        state = AssistantState.model_validate(snapshot.values)
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

    # Tests for ainvoke method
    async def test_ainvoke_basic_functionality(self):
        """Test ainvoke returns all messages at once without streaming."""
        graph = (
            AssistantGraph(self.team, self.user)
            .add_node(AssistantNodeName.ROOT, lambda _: {"messages": [AssistantMessage(content="Response")]})
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile()
        )

        assistant = Assistant(
            self.team,
            self.conversation,
            user=self.user,
            new_message=HumanMessage(content="Test"),
            mode=AssistantMode.INSIGHTS_TOOL,
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
        self.assertEqual(item[1].content, "Response")

    def test_chunk_reasoning_headline(self):
        """Test _chunk_reasoning_headline method with various scenarios."""
        assistant = Assistant(self.team, self.conversation, new_message=HumanMessage(content="Hello"), user=self.user)

        # Test 1: Start of headline - should return None and start chunking
        reasoning = {"summary": [{"text": "**Analyzing user data"}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertEqual(assistant._reasoning_headline_chunk, "Analyzing user data")
        self.assertIsNone(assistant._last_reasoning_headline)

        # Test 2: Continue headline - should return None and continue chunking
        reasoning = {"summary": [{"text": " to find patterns"}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertEqual(assistant._reasoning_headline_chunk, "Analyzing user data to find patterns")
        self.assertIsNone(assistant._last_reasoning_headline)

        # Test 3: End of headline - should return complete headline and reset
        reasoning = {"summary": [{"text": " and insights**"}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertEqual(result, "Analyzing user data to find patterns and insights")
        self.assertIsNone(assistant._reasoning_headline_chunk)
        self.assertEqual(assistant._last_reasoning_headline, "Analyzing user data to find patterns and insights")

        # Test 4: Complete headline in one chunk - should return complete headline immediately
        assistant._reasoning_headline_chunk = None
        assistant._last_reasoning_headline = None
        reasoning = {"summary": [{"text": "**Complete headline in one chunk**"}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertEqual(result, "Complete headline in one chunk")
        self.assertIsNone(assistant._reasoning_headline_chunk)
        self.assertEqual(assistant._last_reasoning_headline, "Complete headline in one chunk")

        # Test 5: Malformed reasoning - missing summary key
        assistant._reasoning_headline_chunk = "Some partial text"
        reasoning = {}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertIsNone(assistant._reasoning_headline_chunk)  # Should reset on error

        # Test 6: Malformed reasoning - empty summary array
        assistant._reasoning_headline_chunk = "Some partial text"
        reasoning = {"summary": []}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertIsNone(assistant._reasoning_headline_chunk)  # Should reset on error

        # Test 7: Malformed reasoning - missing text key
        assistant._reasoning_headline_chunk = "Some partial text"
        reasoning = {"summary": [{}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertIsNone(assistant._reasoning_headline_chunk)  # Should reset on error

        # Test 8: No bold markers in text - should return None
        assistant._reasoning_headline_chunk = None
        reasoning = {"summary": [{"text": "Regular text without bold markers"}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertIsNone(assistant._reasoning_headline_chunk)

        # Test 9: Empty text content
        assistant._reasoning_headline_chunk = None
        reasoning = {"summary": [{"text": ""}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertIsNone(result)
        self.assertIsNone(assistant._reasoning_headline_chunk)

        # Test 10: Only bold markers, no content
        assistant._reasoning_headline_chunk = None
        reasoning = {"summary": [{"text": "****"}]}
        result = assistant._chunk_reasoning_headline(reasoning)
        self.assertEqual(result, "")  # Should return empty headline
        self.assertIsNone(assistant._reasoning_headline_chunk)
        self.assertEqual(assistant._last_reasoning_headline, "")
