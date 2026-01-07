from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AgentMode,
    ArtifactMessage,
    ArtifactSource,
    AssistantEventType,
    AssistantMessage,
    AssistantToolCall,
    AssistantUpdateEvent,
    VisualizationArtifactContent,
)

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.stream.redis_stream import get_subagent_stream_key
from ee.hogai.tools.task import SubagentExecutor, TaskTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath
from ee.models.assistant import Conversation


class TestSubagentExecutor(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def test_executor_sets_stream_key(self):
        tool_call_id = "test_tool_call"
        executor = SubagentExecutor(conversation=self.conversation, tool_call_id=tool_call_id)

        expected_stream_key = get_subagent_stream_key(self.conversation.id, tool_call_id)
        assert executor._redis_stream._stream_key == expected_stream_key

    def test_executor_sets_workflow_id(self):
        tool_call_id = "test_tool_call"
        executor = SubagentExecutor(conversation=self.conversation, tool_call_id=tool_call_id)

        expected_workflow_id = f"subagent-{self.conversation.id}-{tool_call_id}"
        assert executor._workflow_id == expected_workflow_id

    def test_executor_disables_reconnect(self):
        executor = SubagentExecutor(conversation=self.conversation, tool_call_id="test")
        assert not executor._reconnectable


class TestTaskTool(ClickhouseTestMixin, NonAtomicBaseTest):
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

        return TaskTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
            config=config,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_arun_impl_success_returns_final_response(self):
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
                title="Test", task="Do something", agent_mode=AgentMode.PRODUCT_ANALYTICS
            )

        assert "Final response" in result_text
        assert artifact is None

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
                title="Test", task="Do something", agent_mode=AgentMode.PRODUCT_ANALYTICS
            )

        assert "Done" in result_text
        assert artifact is None
        assert "short_id_123" in result_text
        assert "Test" in result_text

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
            await tool._arun_impl(title="Test", task="Do something", agent_mode=AgentMode.PRODUCT_ANALYTICS)

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
            await tool._arun_impl(title="Test", task="Do something", agent_mode=AgentMode.PRODUCT_ANALYTICS)

        # Verify update was dispatched
        mock_dispatcher.update.assert_called_with("Processing...")

    async def test_arun_impl_error_handling(self):
        tool = self._create_tool()

        async def mock_astream_error(*args, **kwargs):
            yield (AssistantEventType.MESSAGE, AssistantMessage(content="Foobar", id="msg_1"))
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
                title="Test", task="Do something", agent_mode=AgentMode.PRODUCT_ANALYTICS
            )

        assert "Error running subagent" in result_text
        assert "Stream error" in result_text
        assert artifact is None


class TestTaskToolCreateToolClass(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    async def test_create_tool_class_generates_description_with_modes(self):
        tool = await TaskTool.create_tool_class(team=self.team, user=self.user)

        # Check that description contains agent modes
        assert "product_analytics" in tool.description
        assert "sql" in tool.description
        assert "session_replay" in tool.description

    async def test_create_tool_class_includes_mode_descriptions(self):
        tool = await TaskTool.create_tool_class(team=self.team, user=self.user)

        # Description should contain mode information
        assert "Available modes" in tool.description

    async def test_create_tool_class_passes_through_params(self):
        state = AssistantState(messages=[])
        config = RunnableConfig(configurable={"test": "value"})
        node_path = (NodePath(name="test", tool_call_id="tc_1", message_id="msg_1"),)

        tool = await TaskTool.create_tool_class(
            team=self.team, user=self.user, state=state, config=config, node_path=node_path
        )

        assert tool._state == state
        assert tool._config == config
        assert tool._node_path == node_path
