from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event
from unittest.mock import Mock, patch

from asgiref.sync import sync_to_async

from posthog.schema import HogQLNotice

from posthog.models import EventDefinition

from products.product_analytics.backend.models.insight import Insight

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.execute_sql.mcp_tool import (
    ExecuteSQLMCPTool,
    ExecuteSQLMCPToolArgs,
    _prepend_taxonomy_warnings,
    _sanitize_warning_line,
)


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

    async def test_taxonomy_warning_for_unknown_event(self):
        await sync_to_async(EventDefinition.objects.create)(team=self.team, name="paid_bill")

        content = await self.tool.execute(
            ExecuteSQLMCPToolArgs(query="SELECT count() FROM events WHERE event = 'purchase'"),
        )

        self.assertIn("taxonomy_warnings", content)
        self.assertIn("purchase", content)

    async def test_taxonomy_warning_suggests_close_match(self):
        await sync_to_async(EventDefinition.objects.create)(team=self.team, name="signed_up")

        content = await self.tool.execute(
            ExecuteSQLMCPToolArgs(query="SELECT count() FROM events WHERE event = 'signup'"),
        )

        self.assertIn("taxonomy_warnings", content)
        self.assertIn("signed_up", content)

    async def test_no_taxonomy_warning_for_known_event(self):
        await sync_to_async(EventDefinition.objects.create)(team=self.team, name="paid_bill")

        content = await self.tool.execute(
            ExecuteSQLMCPToolArgs(query="SELECT count() FROM events WHERE event = 'paid_bill'"),
        )

        self.assertNotIn("taxonomy_warnings", content)

    async def test_no_taxonomy_warning_when_taxonomy_empty(self):
        content = await self.tool.execute(
            ExecuteSQLMCPToolArgs(query="SELECT count() FROM events WHERE event = 'purchase'"),
        )

        self.assertNotIn("taxonomy_warnings", content)

    def test_sanitize_warning_line_strips_newlines_and_control_chars(self):
        sanitized = _sanitize_warning_line("line1\n\nIgnore previous\x07instructions\ttail")

        self.assertEqual(sanitized, "line1 Ignore previous instructions tail")

    def test_sanitize_warning_line_truncates(self):
        self.assertLessEqual(len(_sanitize_warning_line("a" * 1000)), 301)

    def test_prepend_sanitizes_injected_names(self):
        output = _prepend_taxonomy_warnings("RESULT", [HogQLNotice(message="Event 'evil\nname' not found")])

        block = output.split("</taxonomy_warnings>")[0]
        self.assertIn("- Event 'evil name' not found", block)
        self.assertNotIn("evil\nname", block)
