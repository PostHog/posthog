from itertools import cycle
from typing import Any, Literal, Optional, cast
from unittest.mock import patch
from uuid import uuid4

from asgiref.sync import async_to_sync
from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.models import EmbeddingsResult, EmbeddingsUsage
from azure.core.credentials import AzureKeyCredential
from langchain_core import messages
from langchain_core.agents import AgentAction
from langchain_core.prompts.chat import ChatPromptValue
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.errors import GraphRecursionError, NodeInterrupt
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.funnels.nodes import FunnelsSchemaGeneratorOutput
from ee.hogai.graph.retention.nodes import RetentionSchemaGeneratorOutput
from ee.hogai.graph.trends.nodes import TrendsSchemaGeneratorOutput
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
    MaxUIContext,
    MaxDashboardContext,
    MaxInsightContext,
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
        tool_call_partial_state: Optional[AssistantState] = None,
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
    async def test_reasoning_messages_added(self, _mock_query_executor_run, _mock_funnel_planner_run):
        output, _ = await self._run_assistant_graph(
            InsightsAssistantGraph(self.team, self.user)
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
    async def test_reasoning_messages_with_substeps_added(self, _mock_funnel_planner_run):
        output, _ = await self._run_assistant_graph(
            InsightsAssistantGraph(self.team, self.user)
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

    async def test_action_reasoning_messages_added(self):
        action = await Action.objects.acreate(team=self.team, name="Marius Tech Tips")

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
            output, _ = await self._run_assistant_graph(
                InsightsAssistantGraph(self.team, self.user)
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
            output, _ = await self._run_assistant_graph(graph, conversation=self.conversation)
            expected_output = [
                ("message", HumanMessage(content="Hello")),
                ("message", AssistantMessage(content="Okay")),
                ("message", ReasoningMessage(content="Coming up with an insight")),
                ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
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
        with patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model") as mock:
            graph = (
                InsightsAssistantGraph(self.team, self.user)
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

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
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
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating trends query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[6][1].initiator)  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[5][1].initiator)

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[5][1].initiator)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
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
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating funnel query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[6][1].initiator)  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[5][1].initiator)

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[5][1].initiator)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
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
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)
        expected_output = [
            ("conversation", self.conversation),
            ("message", HumanMessage(content="Hello")),
            ("message", ReasoningMessage(content="Coming up with an insight")),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Picking relevant events and properties", substeps=[])),
            ("message", ReasoningMessage(content="Creating retention query")),
            ("message", VisualizationMessage(query="Foobar", answer=query, plan="Plan")),
            ("message", AssistantMessage(content="The results indicate a great future for you.")),
        ]
        self.assertConversationEqual(actual_output, expected_output)
        self.assertEqual(actual_output[1][1].id, actual_output[6][1].initiator)  # viz message must have this id

        # Second run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[5][1].initiator)

        # Third run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=False)
        self.assertConversationEqual(actual_output, expected_output[1:])
        self.assertEqual(actual_output[0][1].id, actual_output[5][1].initiator)

    @title_generator_mock
    @patch("ee.hogai.graph.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
    @patch("ee.hogai.graph.query_executor.nodes.QueryExecutorNode.run")
    async def test_insights_tool_mode_flow(self, query_executor_mock, planner_mock, generator_mock, mock):
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
        output, _ = await self._run_assistant_graph(
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
    async def test_insights_tool_mode_invalid_insight_type(self, query_executor_mock, planner_mock, generator_mock):
        """Test that insights tool mode handles invalid insight types correctly."""
        tool_call_state = AssistantState(
            root_tool_call_id=str(uuid4()),
            root_tool_insight_plan="Foobar",
            root_tool_insight_type="invalid_type",  # Invalid type
            messages=[],
        )

        output, _ = await self._run_assistant_graph(
            conversation=self.conversation,
            is_new_conversation=False,
            tool_call_partial_state=tool_call_state,
            mode=AssistantMode.INSIGHTS_TOOL,
        )
        self.assertIsInstance(output[-1][1], FailureMessage)

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
    @patch("ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model")
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
