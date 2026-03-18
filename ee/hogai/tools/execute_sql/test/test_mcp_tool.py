from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.execute_sql.mcp_tool import ExecuteSQLMCPTool, ExecuteSQLMCPToolArgs


class TestExecuteSQLMCPTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ExecuteSQLMCPTool(team=self.team, user=self.user)

    async def test_successful_execution(self):
        _create_event(team=self.team, distinct_id="user1", event="test_event")
        _create_event(team=self.team, distinct_id="user2", event="test_event")

        content = await self.tool.execute(
            ExecuteSQLMCPToolArgs(query="SELECT event, count() as cnt FROM events GROUP BY event"),
        )

        self.assertIn("test_event", content)

    async def test_validation_error_for_invalid_query(self):
        with self.assertRaises(MaxToolRetryableError) as ctx:
            await self.tool.execute(
                ExecuteSQLMCPToolArgs(query="INVALID SQL SYNTAX"),
            )

        self.assertIn("validation failed", str(ctx.exception).lower())

    async def test_validation_error_for_empty_query(self):
        with self.assertRaises(MaxToolRetryableError):
            await self.tool.execute(
                ExecuteSQLMCPToolArgs(query=""),
            )

    async def test_tool_name_and_schema(self):
        self.assertEqual(self.tool.name, "execute_sql")
        self.assertIsNotNone(self.tool.args_schema)

        validated = self.tool.args_schema.model_validate({"query": "SELECT 1"})
        self.assertEqual(validated.query, "SELECT 1")
