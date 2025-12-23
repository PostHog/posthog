from itertools import cycle
from typing import Any, Optional
from uuid import uuid4

from unittest.mock import AsyncMock, patch

from langchain_core import messages
from langchain_core.runnables import RunnableLambda

from posthog.schema import (
    ArtifactMessage,
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantRetentionActionsNode,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    HumanMessage,
    MaxUIContext,
    VisualizationMessage,
)

from posthog.models import Action

from ee.hogai.chat_agent.funnels.nodes import FunnelsSchemaGeneratorOutput
from ee.hogai.chat_agent.retention.nodes import RetentionSchemaGeneratorOutput
from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.hogai.chat_agent.trends.nodes import TrendsSchemaGeneratorOutput
from ee.hogai.insights_assistant import InsightsAssistant
from ee.hogai.test.base import BaseAssistantTest
from ee.hogai.utils.tests import FakeAnthropicRunnableLambdaWithTokenCounter, FakeChatOpenAI
from ee.hogai.utils.types import AssistantOutput, AssistantState
from ee.models.assistant import Conversation

query_executor_mock = patch(
    "ee.hogai.context.insight.context.execute_and_format_query", new=AsyncMock(return_value="Result")
)


class TestChatAgent(BaseAssistantTest):
    async def _run_assistant_graph(
        self,
        message: Optional[str] = "Hello",
        conversation: Optional[Conversation] = None,
        tool_call_partial_state: Optional[AssistantState] = None,
        is_new_conversation: bool = False,
        contextual_tools: Optional[dict[str, Any]] = None,
        ui_context: Optional[MaxUIContext] = None,
        filter_ack_messages: bool = True,
    ) -> tuple[list[AssistantOutput], ChatAgentRunner | InsightsAssistant]:
        assistant = InsightsAssistant(
            self.team,
            conversation or self.conversation,
            new_message=HumanMessage(content=message, ui_context=ui_context) if message is not None else None,
            user=self.user,
            is_new_conversation=is_new_conversation,
            initial_state=tool_call_partial_state,
            contextual_tools=contextual_tools,
        )

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

    @query_executor_mock
    @patch("ee.hogai.chat_agent.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.chat_agent.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.core.agent_modes.executables.AgentExecutable._get_model")
    @patch(
        "ee.hogai.chat_agent.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]")
    )
    async def test_insights_full_trends_flow(self, memory_collector_mock, root_mock, planner_mock, generator_mock):
        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar"},
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
        generator_mock.return_value = RunnableLambda(
            lambda _: TrendsSchemaGeneratorOutput(query=query, name="Test Insight", description="Test Description")
        )

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)

        # Verify output length (conversation + VisualizationMessage + ArtifactMessage)
        self.assertEqual(len(actual_output), 3)

        # Check conversation output
        self.assertEqual(actual_output[0], ("conversation", self.conversation))
        self.assertEqual(actual_output[1][0], "message")
        self.assertIsInstance(actual_output[1][1], VisualizationMessage)
        self.assertEqual(actual_output[2][0], "message")
        self.assertIsInstance(actual_output[2][1], ArtifactMessage)

    @query_executor_mock
    @patch("ee.hogai.chat_agent.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.chat_agent.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.core.agent_modes.executables.AgentExecutable._get_model")
    @patch(
        "ee.hogai.chat_agent.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]")
    )
    async def test_insights_full_funnel_flow(self, memory_collector_mock, root_mock, planner_mock, generator_mock):
        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar"},
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
        generator_mock.return_value = RunnableLambda(
            lambda _: FunnelsSchemaGeneratorOutput(query=query, name="Test Insight", description="Test Description")
        )

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)

        # Verify output length (conversation + VisualizationMessage + ArtifactMessage)
        self.assertEqual(len(actual_output), 3)

        # Check conversation output
        self.assertEqual(actual_output[0], ("conversation", self.conversation))
        self.assertEqual(actual_output[1][0], "message")
        self.assertIsInstance(actual_output[1][1], VisualizationMessage)
        self.assertEqual(actual_output[2][0], "message")
        self.assertIsInstance(actual_output[2][1], ArtifactMessage)

    @query_executor_mock
    @patch("ee.hogai.chat_agent.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.chat_agent.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.core.agent_modes.executables.AgentExecutable._get_model")
    @patch(
        "ee.hogai.chat_agent.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]")
    )
    async def test_insights_full_retention_flow(self, memory_collector_mock, root_mock, planner_mock, generator_mock):
        action = await Action.objects.acreate(team=self.team, name="Marius Tech Tips")

        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar"},
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
        generator_mock.return_value = RunnableLambda(
            lambda _: RetentionSchemaGeneratorOutput(query=query, name="Test Insight", description="Test Description")
        )

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)

        # Verify output length (conversation + VisualizationMessage + ArtifactMessage)
        self.assertEqual(len(actual_output), 3)

        # Check conversation output
        self.assertEqual(actual_output[0], ("conversation", self.conversation))
        self.assertEqual(actual_output[1][0], "message")
        self.assertIsInstance(actual_output[1][1], VisualizationMessage)
        self.assertEqual(actual_output[2][0], "message")
        self.assertIsInstance(actual_output[2][1], ArtifactMessage)

    @query_executor_mock
    @patch("ee.hogai.chat_agent.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.chat_agent.query_planner.nodes.QueryPlannerNode._get_model")
    @patch("ee.hogai.core.agent_modes.executables.AgentExecutable._get_model")
    @patch(
        "ee.hogai.chat_agent.memory.nodes.MemoryCollectorNode._model", return_value=messages.AIMessage(content="[Done]")
    )
    async def test_insights_full_sql_flow(self, memory_collector_mock, root_mock, planner_mock, generator_mock):
        res1 = FakeAnthropicRunnableLambdaWithTokenCounter(
            lambda _: messages.AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "xyz",
                        "name": "create_and_query_insight",
                        "args": {"query_description": "Foobar"},
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
        generator_mock.return_value = RunnableLambda(
            lambda _: {"query": "SELECT 1", "name": "Test Insight", "description": "Test Description"}
        )

        # First run
        actual_output, _ = await self._run_assistant_graph(is_new_conversation=True)

        # Verify output length (conversation + VisualizationMessage + ArtifactMessage)
        self.assertEqual(len(actual_output), 3)

        # Check conversation output
        self.assertEqual(actual_output[0], ("conversation", self.conversation))
        self.assertEqual(actual_output[1][0], "message")
        self.assertIsInstance(actual_output[1][1], VisualizationMessage)
        self.assertEqual(actual_output[2][0], "message")
        self.assertIsInstance(actual_output[2][1], ArtifactMessage)

    @query_executor_mock
    @patch("ee.hogai.chat_agent.schema_generator.nodes.SchemaGeneratorNode._model")
    @patch("ee.hogai.chat_agent.query_planner.nodes.QueryPlannerNode._get_model")
    async def test_insights_tool_mode_flow(self, planner_mock, generator_mock):
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
        generator_mock.return_value = RunnableLambda(
            lambda _: TrendsSchemaGeneratorOutput(query=query, name="Test Insight", description="Test Description")
        )

        # Run in insights tool mode
        output, _ = await self._run_assistant_graph(
            conversation=self.conversation,
            is_new_conversation=False,
            message=None,
            tool_call_partial_state=tool_call_state,
        )
        # Check artifact message (VisualizationMessage + ArtifactMessage + AssistantToolCallMessage)
        self.assertEqual(len(output), 3)
        self.assertEqual(output[0][0], "message")
        viz_msg = output[0][1]
        assert isinstance(viz_msg, VisualizationMessage)
        self.assertEqual(viz_msg.answer, query)
        assert isinstance(output[1][1], ArtifactMessage)
        self.assertEqual(output[2][0], "message")
        self.assertIsInstance(output[2][1], AssistantToolCallMessage)
