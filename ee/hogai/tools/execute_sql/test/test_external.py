from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event

from ee.hogai.tools.execute_sql.external import ExecuteSQLExternalTool


class TestExecuteSQLExternalTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ExecuteSQLExternalTool()

    async def test_successful_execution(self):
        _create_event(team=self.team, distinct_id="user1", event="test_event")
        _create_event(team=self.team, distinct_id="user2", event="test_event")

        result = await self.tool.execute(
            team=self.team,
            user=self.user,
            query="SELECT event, count() as cnt FROM events GROUP BY event",
            viz_title="Event counts",
            viz_description="Count events by type",
        )

        self.assertTrue(result.success)
        self.assertIn("test_event", result.content)
        self.assertIsNotNone(result.data)
        self.assertIn("query", result.data)

    async def test_validation_error_for_invalid_query(self):
        result = await self.tool.execute(
            team=self.team,
            user=self.user,
            query="INVALID SQL SYNTAX",
            viz_title="Test",
            viz_description="Test",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "validation_error")
        self.assertIn("validation failed", result.content.lower())

    async def test_validation_error_for_empty_query(self):
        result = await self.tool.execute(
            team=self.team,
            user=self.user,
            query="",
            viz_title="Test",
            viz_description="Test",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "validation_error")

    async def test_tool_name_and_schema(self):
        self.assertEqual(self.tool.name, "execute_sql")
        self.assertIsNotNone(self.tool.args_schema)

        # Validate schema can parse valid args
        validated = self.tool.args_schema.model_validate(
            {
                "query": "SELECT 1",
                "viz_title": "Test",
                "viz_description": "Test description",
            }
        )
        self.assertEqual(validated.query, "SELECT 1")
