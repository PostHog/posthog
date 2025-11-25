from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantEventType,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    VisualizationArtifactContent,
)

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.stream.redis_stream import get_subagent_stream_key
from ee.hogai.tool import ToolMessagesArtifact
from ee.hogai.tools.subagent import SubagentExecutor, SubagentTool, SubagentToolArgs
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AgentType, ArtifactRefMessage, NodePath
from ee.models.assistant import Conversation


class TestSubagentToolArgs(NonAtomicBaseTest):
    def test_args_validation_with_defaults(self):
        args = SubagentToolArgs(title="Test", task="Do something")
        self.assertEqual(args.title, "Test")
        self.assertEqual(args.task, "Do something")
        self.assertEqual(args.agent_type, AgentType.GENERAL_PURPOSE)

    def test_args_validation_with_explicit_agent_type(self):
        args = SubagentToolArgs(title="Test", task="Do something", agent_type=AgentType.SQL)
        self.assertEqual(args.agent_type, AgentType.SQL)

    def test_args_validation_all_agent_types(self):
        for agent_type in AgentType:
            args = SubagentToolArgs(title="Test", task="Task", agent_type=agent_type)
            self.assertEqual(args.agent_type, agent_type)


class TestSubagentExecutor(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def test_executor_sets_stream_key(self):
        tool_call_id = "test_tool_call"
        executor = SubagentExecutor(conversation=self.conversation, tool_call_id=tool_call_id)

        expected_stream_key = get_subagent_stream_key(self.conversation.id, tool_call_id)
        self.assertEqual(executor._redis_stream._stream_key, expected_stream_key)

    def test_executor_sets_workflow_id(self):
        tool_call_id = "test_tool_call"
        executor = SubagentExecutor(conversation=self.conversation, tool_call_id=tool_call_id)

        expected_workflow_id = f"subagent-{self.conversation.id}-{tool_call_id}"
        self.assertEqual(executor._workflow_id, expected_workflow_id)

    def test_executor_disables_reconnect(self):
        executor = SubagentExecutor(conversation=self.conversation, tool_call_id="test")
        self.assertFalse(executor._can_reconnect)


class TestSubagentTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.tool_call_id = "test_tool_call_id"

    def _create_tool(self, state: AssistantState | None = None):
        if state is None:
            state = AssistantState(messages=[])

        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        return SubagentTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
            config=config,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_arun_impl_success_returns_tool_call_message(self):
        tool = self._create_tool()

        async def mock_astream(*args, **kwargs):
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Final response", id="msg_1"))

        mock_dispatcher = MagicMock()

        with (
            patch.object(SubagentExecutor, "astream", mock_astream),
            patch(
                "ee.hogai.core.mixins.create_dispatcher_from_config",
                return_value=mock_dispatcher,
            ),
        ):
            result_text, artifact = await tool._arun_impl(
                title="Test", task="Do something", agent_type=AgentType.GENERAL_PURPOSE
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        assert isinstance(artifact, ToolMessagesArtifact)
        self.assertEqual(len(artifact.messages), 1)
        self.assertIsInstance(artifact.messages[0], AssistantToolCallMessage)
        assert isinstance(artifact.messages[0], AssistantToolCallMessage)
        self.assertEqual(artifact.messages[0].content, "Final response")
        self.assertEqual(artifact.messages[0].tool_call_id, self.tool_call_id)

    async def test_arun_impl_handles_artifact_messages(self):
        tool = self._create_tool()

        from posthog.schema import AssistantTrendsQuery

        artifact_message = ArtifactMessage(
            id="artifact_1",
            artifact_id="short_id_123",
            source=ArtifactSource.ARTIFACT,
            content=VisualizationArtifactContent(
                query=AssistantTrendsQuery(series=[]),
                name="Test",
                description="Test",
            ),
        )

        async def mock_astream(*args, **kwargs):
            yield (AssistantEventType.MESSAGE, artifact_message)
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Done", id="msg_1"))

        mock_dispatcher = MagicMock()

        with (
            patch.object(SubagentExecutor, "astream", mock_astream),
            patch(
                "ee.hogai.core.mixins.create_dispatcher_from_config",
                return_value=mock_dispatcher,
            ),
        ):
            result_text, artifact = await tool._arun_impl(
                title="Test", task="Do something", agent_type=AgentType.GENERAL_PURPOSE
            )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact)
        assert isinstance(artifact, ToolMessagesArtifact)
        self.assertEqual(len(artifact.messages), 2)

        # First should be ArtifactRefMessage
        self.assertIsInstance(artifact.messages[0], ArtifactRefMessage)
        assert isinstance(artifact.messages[0], ArtifactRefMessage)
        self.assertEqual(artifact.messages[0].artifact_id, "short_id_123")
        self.assertEqual(artifact.messages[0].source, ArtifactSource.ARTIFACT)
        self.assertEqual(artifact.messages[0].content_type, ArtifactContentType.VISUALIZATION)

        # Second should be AssistantToolCallMessage
        self.assertIsInstance(artifact.messages[1], AssistantToolCallMessage)
        assert isinstance(artifact.messages[1], AssistantToolCallMessage)
        self.assertEqual(artifact.messages[1].content, "Done")

        # Verify dispatcher was called with artifact message
        mock_dispatcher.message.assert_called_once()

    async def test_arun_impl_dispatches_tool_call_updates(self):
        tool = self._create_tool()

        tool_call = AssistantToolCall(id="tc_1", name="some_tool", args={})
        message_with_tool_calls = AssistantMessage(content="Calling tool", id="msg_1", tool_calls=[tool_call])

        async def mock_astream(*args, **kwargs):
            yield (AssistantEventType.MESSAGE, message_with_tool_calls)
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Final", id="msg_2"))

        mock_dispatcher = MagicMock()

        with (
            patch.object(SubagentExecutor, "astream", mock_astream),
            patch(
                "ee.hogai.core.mixins.create_dispatcher_from_config",
                return_value=mock_dispatcher,
            ),
        ):
            await tool._arun_impl(title="Test", task="Do something", agent_type=AgentType.GENERAL_PURPOSE)

        # Verify tool call was dispatched as update
        mock_dispatcher.update.assert_called_with(content=tool_call)

    async def test_arun_impl_dispatches_update_events(self):
        tool = self._create_tool()

        update_event = AssistantUpdateEvent(content="Processing...", id="update_1", tool_call_id="tc_1")

        async def mock_astream(*args, **kwargs):
            yield (AssistantEventType.UPDATE, update_event)
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Done", id="msg_1"))

        mock_dispatcher = MagicMock()

        with (
            patch.object(SubagentExecutor, "astream", mock_astream),
            patch(
                "ee.hogai.core.mixins.create_dispatcher_from_config",
                return_value=mock_dispatcher,
            ),
        ):
            await tool._arun_impl(title="Test", task="Do something", agent_type=AgentType.GENERAL_PURPOSE)

        # Verify update was dispatched
        mock_dispatcher.update.assert_called_with("Processing...")

    async def test_arun_impl_skips_messages_without_id(self):
        tool = self._create_tool()

        async def mock_astream(*args, **kwargs):
            # Message without ID should be skipped
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Incomplete", id=None))
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Complete", id="msg_1"))

        mock_dispatcher = MagicMock()

        with (
            patch.object(SubagentExecutor, "astream", mock_astream),
            patch(
                "ee.hogai.core.mixins.create_dispatcher_from_config",
                return_value=mock_dispatcher,
            ),
        ):
            result_text, artifact = await tool._arun_impl(
                title="Test", task="Do something", agent_type=AgentType.GENERAL_PURPOSE
            )

        # Should only have the complete message
        assert isinstance(artifact, ToolMessagesArtifact)
        assert isinstance(artifact.messages[0], AssistantToolCallMessage)
        self.assertEqual(artifact.messages[0].content, "Complete")

    async def test_arun_impl_error_handling(self):
        tool = self._create_tool()

        async def mock_astream_error(*args, **kwargs):
            if False:
                yield  # Make this an async generator
            raise Exception("Stream error")

        mock_dispatcher = MagicMock()

        with (
            patch.object(SubagentExecutor, "astream", mock_astream_error),
            patch(
                "ee.hogai.core.mixins.create_dispatcher_from_config",
                return_value=mock_dispatcher,
            ),
        ):
            result_text, artifact = await tool._arun_impl(
                title="Test", task="Do something", agent_type=AgentType.GENERAL_PURPOSE
            )

        self.assertIn("Error running subagent", result_text)
        self.assertIn("Stream error", result_text)
        self.assertIsNone(artifact)


class TestSubagentToolCreateToolClass(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    async def test_create_tool_class_generates_description_with_agents(self):
        tool = await SubagentTool.create_tool_class(team=self.team, user=self.user)

        # Check that description contains agent types
        self.assertIn("general_purpose", tool.description)
        self.assertIn("sql", tool.description)
        self.assertIn("session_replay", tool.description)

    async def test_create_tool_class_includes_mode_descriptions(self):
        tool = await SubagentTool.create_tool_class(team=self.team, user=self.user)

        # Description should contain mode information
        self.assertIn("Available modes", tool.description)

    async def test_create_tool_class_passes_through_params(self):
        state = AssistantState(messages=[])
        config = RunnableConfig(configurable={"test": "value"})
        node_path = (NodePath(name="test", tool_call_id="tc_1", message_id="msg_1"),)

        tool = await SubagentTool.create_tool_class(
            team=self.team, user=self.user, state=state, config=config, node_path=node_path
        )

        self.assertEqual(tool._state, state)
        self.assertEqual(tool._config, config)
        self.assertEqual(tool._node_path, node_path)
