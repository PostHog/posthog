from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import ArtifactContentType, AssistantToolCallMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.execute_sql.tool import ExecuteSQLTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath
from ee.models import Conversation


class TestExecuteSQLTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    async def _create_tool(self, state: AssistantState | None = None):
        if state is None:
            state = AssistantState(messages=[])

        config: RunnableConfig = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        with patch.object(context_manager, "get_group_names", AsyncMock(return_value=["organization", "project"])):
            tool = await ExecuteSQLTool.create_tool_class(
                team=self.team,
                user=self.user,
                state=state,
                config=config,
                context_manager=context_manager,
                node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
            )
        return tool

    async def test_successful_sql_execution_returns_messages(self):
        _create_event(team=self.team, distinct_id="user1", event="test_event")
        _create_event(team=self.team, distinct_id="user2", event="test_event")
        _create_event(team=self.team, distinct_id="user3", event="another_event")

        tool = await self._create_tool()

        result_text, artifact_messages = await tool._arun_impl(
            "SELECT event, count() as count FROM events GROUP BY event ORDER BY count DESC",
            "Event counts",
            "Count events by type",
        )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact_messages)
        self.assertEqual(len(artifact_messages.messages), 2)
        self.assertEqual(artifact_messages.messages[0].content_type, ArtifactContentType.VISUALIZATION)
        self.assertIsInstance(artifact_messages.messages[1], AssistantToolCallMessage)
        self.assertIn("test_event", artifact_messages.messages[1].content)
        self.assertIn("another_event", artifact_messages.messages[1].content)

    async def test_artifact_id_in_output(self):
        _create_event(team=self.team, distinct_id="user1", event="test_event")

        tool = await self._create_tool()

        result_text, artifact_messages = await tool._arun_impl(
            "SELECT event, count() as count FROM events GROUP BY event",
            "Test query",
            "Test description",
        )

        self.assertEqual(result_text, "")
        self.assertIsNotNone(artifact_messages)
        self.assertEqual(len(artifact_messages.messages), 2)

        # Get artifact_id from the first message
        artifact_id = artifact_messages.messages[0].artifact_id
        self.assertIsNotNone(artifact_id)

        # Verify artifact_id is included in the second message content
        tool_call_content = artifact_messages.messages[1].content
        self.assertIn(artifact_id, tool_call_content)
