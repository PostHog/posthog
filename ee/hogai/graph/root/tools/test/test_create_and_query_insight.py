from typing import Any
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantMessage,
    AssistantTool,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    VisualizationMessage,
)

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.root.tools.create_and_query_insight import (
    INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT,
    CreateAndQueryInsightTool,
)
from ee.hogai.graph.schema_generator.nodes import SchemaGenerationException
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation


class TestCreateAndQueryInsightTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.tool_call_id = str(uuid4())

    def _create_tool(
        self, state: AssistantState | None = None, contextual_tools: dict[str, dict[str, Any]] | None = None
    ):
        """Helper to create tool instance with optional state and contextual tools."""
        if state is None:
            state = AssistantState(messages=[])

        config: RunnableConfig = RunnableConfig()
        if contextual_tools:
            config = RunnableConfig(configurable={"contextual_tools": contextual_tools})

        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        return CreateAndQueryInsightTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

    async def test_successful_insight_creation_returns_messages(self):
        """Test successful insight creation returns visualization and tool call messages."""
        tool = self._create_tool()

        query = AssistantTrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")
        tool_call_message = AssistantToolCallMessage(content="Results are here", tool_call_id=self.tool_call_id)

        mock_state = AssistantState(messages=[viz_message, tool_call_message])

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_compile.return_value = mock_graph

            result_text, artifact = await tool._arun_impl(
                query_description="test description", tool_call_id=self.tool_call_id
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        self.assertEqual(len(artifact.messages), 2)
        self.assertIsInstance(artifact.messages[0], VisualizationMessage)
        self.assertIsInstance(artifact.messages[1], AssistantToolCallMessage)

    async def test_schema_generation_exception_returns_formatted_error(self):
        """Test SchemaGenerationException is caught and returns formatted error message."""
        tool = self._create_tool()

        exception = SchemaGenerationException(
            llm_output="Invalid query structure", validation_message="Missing required field: series"
        )

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(side_effect=exception)
            mock_compile.return_value = mock_graph

            result_text, artifact = await tool._arun_impl(
                query_description="test description", tool_call_id=self.tool_call_id
            )

        self.assertIsNone(artifact)
        self.assertIn("Invalid query structure", result_text)
        self.assertIn("Missing required field: series", result_text)
        self.assertIn(INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT, result_text)

    async def test_invalid_tool_call_message_type_returns_error(self):
        """Test when the last message is not AssistantToolCallMessage, returns error."""
        tool = self._create_tool()

        viz_message = VisualizationMessage(query="test query", answer=AssistantTrendsQuery(series=[]), plan="test plan")
        # Last message is AssistantMessage instead of AssistantToolCallMessage
        invalid_message = AssistantMessage(content="Not a tool call message")

        mock_state = AssistantState(messages=[viz_message, invalid_message])

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_compile.return_value = mock_graph

            result_text, artifact = await tool._arun_impl(
                query_description="test description", tool_call_id=self.tool_call_id
            )

        self.assertIsNone(artifact)
        self.assertIn("unknown error", result_text)
        self.assertIn(INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT, result_text)

    async def test_human_feedback_requested_returns_only_tool_call_message(self):
        """Test when visualization message is not present, returns only tool call message."""
        tool = self._create_tool()

        # When agent requests human feedback, there's no VisualizationMessage
        some_message = AssistantMessage(content="I need help with this query")
        tool_call_message = AssistantToolCallMessage(content="Need clarification", tool_call_id=self.tool_call_id)

        mock_state = AssistantState(messages=[some_message, tool_call_message])

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_compile.return_value = mock_graph

            result_text, artifact = await tool._arun_impl(
                query_description="test description", tool_call_id=self.tool_call_id
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        self.assertEqual(len(artifact.messages), 1)
        self.assertIsInstance(artifact.messages[0], AssistantToolCallMessage)
        self.assertEqual(artifact.messages[0].content, "Need clarification")

    async def test_editing_mode_adds_ui_payload(self):
        """Test that in editing mode, UI payload is added to tool call message."""
        # Create tool with contextual tool available
        tool = self._create_tool(contextual_tools={AssistantTool.CREATE_AND_QUERY_INSIGHT.value: {}})

        query = AssistantTrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")
        tool_call_message = AssistantToolCallMessage(content="Results are here", tool_call_id=self.tool_call_id)

        mock_state = AssistantState(messages=[viz_message, tool_call_message])

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_compile.return_value = mock_graph

            result_text, artifact = await tool._arun_impl(
                query_description="test description", tool_call_id=self.tool_call_id
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        self.assertEqual(len(artifact.messages), 2)

        # Check that UI payload was added to tool call message
        returned_tool_call_message = artifact.messages[1]
        self.assertIsInstance(returned_tool_call_message, AssistantToolCallMessage)
        self.assertIsNotNone(returned_tool_call_message.ui_payload)
        self.assertIn("create_and_query_insight", returned_tool_call_message.ui_payload)
        self.assertEqual(
            returned_tool_call_message.ui_payload["create_and_query_insight"], query.model_dump(exclude_none=True)
        )
        # Visible defaults to True (show_tool_call_message is True by default)
        self.assertTrue(returned_tool_call_message.visible)

    async def test_non_editing_mode_no_ui_payload(self):
        """Test that in non-editing mode, no UI payload is added to tool call message."""
        # Create tool without contextual tools (non-editing mode)
        tool = self._create_tool(contextual_tools={})

        query = AssistantTrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")
        tool_call_message = AssistantToolCallMessage(content="Results are here", tool_call_id=self.tool_call_id)

        mock_state = AssistantState(messages=[viz_message, tool_call_message])

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_state.model_dump())
            mock_compile.return_value = mock_graph

            result_text, artifact = await tool._arun_impl(
                query_description="test description", tool_call_id=self.tool_call_id
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        self.assertEqual(len(artifact.messages), 2)

        # Check that the original tool call message is returned without modification
        returned_tool_call_message = artifact.messages[1]
        self.assertIsInstance(returned_tool_call_message, AssistantToolCallMessage)
        # In non-editing mode, the original message is returned as-is
        self.assertEqual(returned_tool_call_message, tool_call_message)

    async def test_state_updates_include_tool_call_metadata(self):
        """Test that the state passed to graph includes root_tool_call_id and root_tool_insight_plan."""
        initial_state = AssistantState(messages=[AssistantMessage(content="initial")])
        tool = self._create_tool(state=initial_state)

        query = AssistantTrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")
        tool_call_message = AssistantToolCallMessage(content="Results", tool_call_id=self.tool_call_id)
        mock_state = AssistantState(messages=[viz_message, tool_call_message])

        invoked_state = None

        async def capture_invoked_state(state):
            nonlocal invoked_state
            invoked_state = state
            return mock_state.model_dump()

        with patch("ee.hogai.graph.insights_graph.graph.InsightsGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(side_effect=capture_invoked_state)
            mock_compile.return_value = mock_graph

            await tool._arun_impl(query_description="my test query", tool_call_id=self.tool_call_id)

        # Verify the state passed to ainvoke has the correct metadata
        self.assertIsNotNone(invoked_state)
        validated_state = AssistantState.model_validate(invoked_state)
        self.assertEqual(validated_state.root_tool_call_id, self.tool_call_id)
        self.assertEqual(validated_state.root_tool_insight_plan, "my test query")
        # Original message should still be there
        self.assertEqual(len(validated_state.messages), 1)
        assert isinstance(validated_state.messages[0], AssistantMessage)
        self.assertEqual(validated_state.messages[0].content, "initial")

    async def test_is_editing_mode_classmethod(self):
        """Test the is_editing_mode class method correctly detects editing mode."""
        # Test with editing mode enabled
        config_editing: RunnableConfig = RunnableConfig(
            configurable={"contextual_tools": {AssistantTool.CREATE_AND_QUERY_INSIGHT.value: {}}}
        )
        context_manager_editing = AssistantContextManager(team=self.team, user=self.user, config=config_editing)
        self.assertTrue(CreateAndQueryInsightTool.is_editing_mode(context_manager_editing))

        # Test with editing mode disabled
        config_not_editing = RunnableConfig(configurable={"contextual_tools": {}})
        context_manager_not_editing = AssistantContextManager(team=self.team, user=self.user, config=config_not_editing)
        self.assertFalse(CreateAndQueryInsightTool.is_editing_mode(context_manager_not_editing))

        # Test with other contextual tools but not create_and_query_insight
        config_other = RunnableConfig(configurable={"contextual_tools": {"some_other_tool": {}}})
        context_manager_other = AssistantContextManager(team=self.team, user=self.user, config=config_other)
        self.assertFalse(CreateAndQueryInsightTool.is_editing_mode(context_manager_other))
