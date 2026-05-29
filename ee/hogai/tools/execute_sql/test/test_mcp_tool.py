from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event
from unittest.mock import AsyncMock, Mock, patch

from asgiref.sync import sync_to_async

from posthog.schema import HogQLQuery

from products.product_analytics.backend.models.insight import Insight

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

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    async def test_select_from_system_insights(self):
        await sync_to_async(Insight.objects.create)(
            team=self.team,
            name="Revenue Trends",
            query={"kind": "TrendsQuery", "series": [{"event": "$pageview", "kind": "EventsNode"}]},
        )

        content = await self.tool.execute(
            ExecuteSQLMCPToolArgs(query="SELECT id, name FROM system.insights"),
        )

        self.assertIn("Revenue Trends", content)

    async def test_connection_id_skips_local_validation_and_wraps_in_hogql_query(self):
        # When a connectionId is set the query may reference tables that only exist on the
        # external connection, so we must bypass the local HogQL parse/print step and pass
        # a real HogQLQuery (which carries connectionId) down to the runner.
        captured: dict = {}

        async def fake_execute_and_format(self, *args, **kwargs):
            captured["query"] = self.query
            return "ok"

        with (
            patch(
                "ee.hogai.tools.execute_sql.mcp_tool.InsightContext.execute_and_format",
                new=fake_execute_and_format,
            ),
            patch.object(self.tool, "_validate_hogql_query", new=AsyncMock()) as validate_mock,
        ):
            result = await self.tool.execute(
                ExecuteSQLMCPToolArgs(query="SELECT * FROM ducklake_orders", connectionId="conn_abc"),
            )

        self.assertEqual(result, "ok")
        validate_mock.assert_not_awaited()
        self.assertIsInstance(captured["query"], HogQLQuery)
        self.assertEqual(captured["query"].connectionId, "conn_abc")
        self.assertEqual(captured["query"].query, "SELECT * FROM ducklake_orders")

    async def test_connection_id_with_empty_query_raises(self):
        with self.assertRaises(MaxToolRetryableError):
            await self.tool.execute(
                ExecuteSQLMCPToolArgs(query="   ", connectionId="conn_abc"),
            )
