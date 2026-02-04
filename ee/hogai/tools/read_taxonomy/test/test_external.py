from posthog.test.base import NonAtomicBaseTest

from ee.hogai.tools.read_taxonomy.external import ReadTaxonomyExternalTool


class TestReadTaxonomyExternalTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ReadTaxonomyExternalTool()

    async def test_tool_has_correct_name(self):
        self.assertEqual(self.tool.name, "read_taxonomy")

    async def test_read_events_returns_yaml(self):
        result = await self.tool.execute(
            team=self.team,
            user=self.user,
            query={"kind": "events"},
        )

        self.assertTrue(result.success)
        self.assertIn("events:", result.content)
        self.assertIsNotNone(result.data)
        self.assertEqual(result.data["query"], {"kind": "events"})

    async def test_invalid_query_returns_validation_error(self):
        result = await self.tool.execute(
            team=self.team,
            user=self.user,
            query={"kind": "invalid_kind"},
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "validation_error")

    async def test_schema_validates_query(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events"}})
        self.assertEqual(validated.query.kind, "events")

        validated = self.tool.args_schema.model_validate(
            {"query": {"kind": "event_properties", "event_name": "$pageview"}}
        )
        self.assertEqual(validated.query.kind, "event_properties")
        self.assertEqual(validated.query.event_name, "$pageview")
