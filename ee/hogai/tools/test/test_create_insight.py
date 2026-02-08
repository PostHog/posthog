from typing import Any

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantMessage,
    AssistantTool,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    VisualizationArtifactContent,
)

from ee.hogai.chat_agent.schema_generator.nodes import SchemaGenerationException
from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.create_insight import INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT, CreateInsightTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantNodeName, NodePath
from ee.models import AgentArtifact, Conversation


class TestCreateInsightTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    async def _create_tool(
        self, state: AssistantState | None = None, contextual_tools: dict[str, dict[str, Any]] | None = None
    ):
        """Helper to create tool instance with optional state and contextual tools."""
        if state is None:
            state = AssistantState(messages=[])

        config: RunnableConfig = RunnableConfig()
        if contextual_tools:
            config = RunnableConfig(configurable={"contextual_tools": contextual_tools})

        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        with patch.object(context_manager, "get_group_names", AsyncMock(return_value=["organization", "project"])):
            tool = await CreateInsightTool.create_tool_class(
                team=self.team,
                user=self.user,
                state=state,
                config=config,
                context_manager=context_manager,
                node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
            )
        return tool

    async def test_successful_trends_insight_creation_returns_messages(self):
        """Test successful trends insight creation returns visualization and tool call messages."""
        tool = await self._create_tool()

        query = AssistantTrendsQuery(series=[])
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(query=query, name="Query 1", description="Plan 1").model_dump(),
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        tool_call_message = AssistantToolCallMessage(content="Results are here", tool_call_id=self.tool_call_id)

        mock_state = AssistantState(messages=[artifact_message, tool_call_message])

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_trends_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_graph_builder.compile.return_value = mock_compiled_graph

            result_text, artifact = await tool._arun_impl(
                viz_title="Test Chart",
                viz_description="Test description",
                query_description="test trends description",
                insight_type="trends",
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        self.assertEqual(len(artifact.messages), 2)
        self.assertIsInstance(artifact.messages[0], ArtifactRefMessage)
        self.assertIsInstance(artifact.messages[1], AssistantToolCallMessage)

        # Verify correct graph nodes were added
        mock_graph_builder.add_trends_generator.assert_called_once()
        mock_graph_builder.add_edge.assert_called_with(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)

    async def test_successful_funnel_insight_creation_returns_messages(self):
        """Test successful funnel insight creation uses correct generator node."""
        tool = await self._create_tool()

        query = AssistantTrendsQuery(series=[])
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(query=query, name="Query 1", description="Plan 1").model_dump(),
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        tool_call_message = AssistantToolCallMessage(content="Results", tool_call_id=self.tool_call_id)
        mock_state = AssistantState(messages=[artifact_message, tool_call_message])

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_funnel_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_graph_builder.compile.return_value = mock_compiled_graph

            await tool._arun_impl(
                viz_title="Test Funnel",
                viz_description="Test description",
                query_description="test funnel",
                insight_type="funnel",
            )

        mock_graph_builder.add_funnel_generator.assert_called_once()
        mock_graph_builder.add_edge.assert_called_with(AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR)

    async def test_successful_retention_insight_creation_returns_messages(self):
        """Test successful retention insight creation uses correct generator node."""
        tool = await self._create_tool()

        query = AssistantTrendsQuery(series=[])
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(query=query, name="Query 1", description="Plan 1").model_dump(),
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        tool_call_message = AssistantToolCallMessage(content="Results", tool_call_id=self.tool_call_id)
        mock_state = AssistantState(messages=[artifact_message, tool_call_message])

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_retention_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_graph_builder.compile.return_value = mock_compiled_graph

            await tool._arun_impl(
                viz_title="Test Retention",
                viz_description="Test description",
                query_description="test retention",
                insight_type="retention",
            )

        mock_graph_builder.add_retention_generator.assert_called_once()
        mock_graph_builder.add_edge.assert_called_with(AssistantNodeName.START, AssistantNodeName.RETENTION_GENERATOR)

    async def test_schema_generation_exception_returns_formatted_error(self):
        """Test SchemaGenerationException is caught and returns formatted error message."""
        tool = await self._create_tool()

        exception = SchemaGenerationException(
            llm_output="Invalid query structure", validation_message="Missing required field: series"
        )

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_trends_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(side_effect=exception)
            mock_graph_builder.compile.return_value = mock_compiled_graph

            result_text, artifact = await tool._arun_impl(
                viz_title="Test Chart",
                viz_description="Test description",
                query_description="test description",
                insight_type="trends",
            )

        self.assertIsNone(artifact)
        self.assertIn("Invalid query structure", result_text)
        self.assertIn("Missing required field: series", result_text)
        self.assertIn(INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT, result_text)

    async def test_invalid_tool_call_message_type_returns_error(self):
        """Test when the last message is not AssistantToolCallMessage, returns error."""
        tool = await self._create_tool()

        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=AssistantTrendsQuery(series=[]), name="Query 1", description="Plan 1"
            ).model_dump(),
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        invalid_message = AssistantMessage(content="Not a tool call message")
        mock_state = AssistantState(messages=[artifact_message, invalid_message])

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_trends_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_graph_builder.compile.return_value = mock_compiled_graph

            result_text, artifact = await tool._arun_impl(
                viz_title="Test Chart",
                viz_description="Test description",
                query_description="test description",
                insight_type="trends",
            )

        self.assertIsNone(artifact)
        self.assertIn("unknown error", result_text)
        self.assertIn(INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT, result_text)

    async def test_human_feedback_requested_returns_only_tool_call_message(self):
        """Test when visualization message is not present, returns only tool call message."""
        tool = await self._create_tool()

        some_message = AssistantMessage(content="I need help with this query")
        tool_call_message = AssistantToolCallMessage(content="Need clarification", tool_call_id=self.tool_call_id)
        mock_state = AssistantState(messages=[some_message, tool_call_message])

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_funnel_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_graph_builder.compile.return_value = mock_compiled_graph

            result_text, artifact = await tool._arun_impl(
                viz_title="Test Chart",
                viz_description="Test description",
                query_description="test description",
                insight_type="funnel",
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        self.assertEqual(len(artifact.messages), 1)
        self.assertIsInstance(artifact.messages[0], AssistantToolCallMessage)
        self.assertEqual(artifact.messages[0].content, "Need clarification")

    async def test_editing_mode_adds_ui_payload(self):
        """Test that in editing mode, UI payload is added to tool call message."""
        tool = await self._create_tool(contextual_tools={AssistantTool.CREATE_INSIGHT.value: {}})

        query = AssistantTrendsQuery(series=[])
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(query=query, name="Query 1", description="Plan 1").model_dump(),
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        tool_call_message = AssistantToolCallMessage(content="Results are here", tool_call_id=self.tool_call_id)
        mock_state = AssistantState(messages=[artifact_message, tool_call_message])

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_trends_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_graph_builder.compile.return_value = mock_compiled_graph

            result_text, artifact = await tool._arun_impl(
                viz_title="Test Chart",
                viz_description="Test description",
                query_description="test description",
                insight_type="trends",
            )

        self.assertIsNotNone(artifact)
        returned_tool_call_message = artifact.messages[1]
        self.assertIsInstance(returned_tool_call_message, AssistantToolCallMessage)
        self.assertIsNotNone(returned_tool_call_message.ui_payload)
        self.assertIn("create_insight", returned_tool_call_message.ui_payload)
        self.assertEqual(returned_tool_call_message.ui_payload["create_insight"], query.model_dump(exclude_none=True))

    async def test_state_updates_include_tool_call_metadata(self):
        """Test that the state passed to graph includes root_tool_call_id and plan."""
        initial_state = AssistantState(messages=[AssistantMessage(content="initial")])
        tool = await self._create_tool(state=initial_state)

        query = AssistantTrendsQuery(series=[])
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(query=query, name="Query 1", description="Plan 1").model_dump(),
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        tool_call_message = AssistantToolCallMessage(content="Results", tool_call_id=self.tool_call_id)
        mock_state = AssistantState(messages=[artifact_message, tool_call_message])

        invoked_state = None

        async def capture_invoked_state(state):
            nonlocal invoked_state
            invoked_state = state
            return mock_state.model_dump()

        with patch("ee.hogai.tools.create_insight.InsightsGraph") as mock_graph_class:
            mock_graph_builder = mock_graph_class.return_value
            mock_graph_builder.add_retention_generator.return_value = mock_graph_builder
            mock_graph_builder.add_edge.return_value = mock_graph_builder
            mock_graph_builder.add_query_executor.return_value = mock_graph_builder

            mock_compiled_graph = AsyncMock()
            mock_compiled_graph.ainvoke = AsyncMock(side_effect=capture_invoked_state)
            mock_graph_builder.compile.return_value = mock_compiled_graph

            await tool._arun_impl(
                viz_title="Test Chart",
                viz_description="Test description",
                query_description="my test query",
                insight_type="retention",
            )

        self.assertIsNotNone(invoked_state)
        validated_state = AssistantState.model_validate(invoked_state)
        self.assertEqual(validated_state.root_tool_call_id, self.tool_call_id)
        self.assertEqual(validated_state.plan, "my test query")
        self.assertEqual(len(validated_state.messages), 1)
        assert isinstance(validated_state.messages[0], AssistantMessage)
        self.assertEqual(validated_state.messages[0].content, "initial")

    async def test_is_editing_mode_detection(self):
        """Test that is_editing_mode correctly detects editing mode."""
        config_editing: RunnableConfig = RunnableConfig(
            configurable={"contextual_tools": {AssistantTool.CREATE_INSIGHT.value: {}}}
        )
        context_manager_editing = AssistantContextManager(team=self.team, user=self.user, config=config_editing)
        self.assertTrue(CreateInsightTool.is_editing_mode(context_manager_editing))

        config_not_editing = RunnableConfig(configurable={"contextual_tools": {}})
        context_manager_not_editing = AssistantContextManager(team=self.team, user=self.user, config=config_not_editing)
        self.assertFalse(CreateInsightTool.is_editing_mode(context_manager_not_editing))
