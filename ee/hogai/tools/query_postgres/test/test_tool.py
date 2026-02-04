from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.query_postgres.tool import QueryPostgresTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath
from ee.models import Conversation


class TestQueryPostgresTool(BaseTest):
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
            tool = await QueryPostgresTool.create_tool_class(
                team=self.team,
                user=self.user,
                state=state,
                config=config,
                context_manager=context_manager,
                node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
            )
        return tool

    async def test_tool_creation(self):
        tool = await self._create_tool()
        self.assertEqual(tool.name, "query_postgres")
        self.assertIn("PostgreSQL", tool.description)

    @patch("ee.hogai.tools.query_postgres.tool.execute_postgres_query")
    async def test_successful_query_returns_results(self, mock_execute):
        # Mock successful query result
        from posthog.hogql.postgres_executor import PostgresQueryResult

        mock_execute.return_value = PostgresQueryResult(
            columns=["name", "description"],
            rows=[
                {"name": "Dashboard 1", "description": "Test dashboard"},
                {"name": "Dashboard 2", "description": "Another dashboard"},
            ],
            row_count=2,
            truncated=False,
        )

        tool = await self._create_tool()
        result_text, artifact_messages = await tool._arun_impl("SELECT name, description FROM dashboard LIMIT 10")

        # Verify execution was called with correct parameters
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        self.assertEqual(call_args.kwargs["query"], "SELECT name, description FROM dashboard LIMIT 10")
        self.assertEqual(call_args.kwargs["team"], self.team)
        self.assertEqual(call_args.kwargs["user"], self.user)

        # Verify result format
        self.assertIn("Dashboard 1", result_text)
        self.assertIn("Dashboard 2", result_text)
        self.assertIsNotNone(artifact_messages)
        self.assertEqual(len(artifact_messages.messages), 1)
        self.assertIsInstance(artifact_messages.messages[0], AssistantToolCallMessage)

    @patch("ee.hogai.tools.query_postgres.tool.execute_postgres_query")
    async def test_query_error_returns_recoverable_error(self, mock_execute):
        from posthog.hogql.errors import QueryError

        mock_execute.side_effect = QueryError("Unknown table 'nonexistent'")

        tool = await self._create_tool()
        result_text, artifact_messages = await tool._arun_impl("SELECT * FROM nonexistent")

        self.assertIn("query failed", result_text.lower())
        self.assertIn("Unknown table", result_text)
        self.assertIsNone(artifact_messages)

    @patch("ee.hogai.tools.query_postgres.tool.execute_postgres_query")
    async def test_unexpected_error_returns_unrecoverable_error(self, mock_execute):
        mock_execute.side_effect = Exception("Database connection failed")

        tool = await self._create_tool()
        result_text, artifact_messages = await tool._arun_impl("SELECT * FROM dashboard")

        self.assertIn("unexpected error", result_text.lower())
        self.assertIsNone(artifact_messages)

    @patch("ee.hogai.tools.query_postgres.tool.execute_postgres_query")
    async def test_truncated_results_noted(self, mock_execute):
        from posthog.hogql.postgres_executor import PostgresQueryResult

        mock_execute.return_value = PostgresQueryResult(
            columns=["id"],
            rows=[{"id": i} for i in range(100)],
            row_count=100,
            truncated=True,
        )

        tool = await self._create_tool()
        result_text, artifact_messages = await tool._arun_impl("SELECT id FROM dashboard")

        self.assertIn("truncated", result_text.lower())
        self.assertIsNotNone(artifact_messages)
        self.assertIn("truncated", artifact_messages.messages[0].content.lower())
