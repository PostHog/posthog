from posthog.test.base import NonAtomicBaseTest

from ee.hogai.tools.read_taxonomy.core import ReadEventProperties, ReadTaxonomyToolArgs
from ee.hogai.tools.read_taxonomy.mcp_tool import ReadTaxonomyMCPTool


class TestReadTaxonomyMCPTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ReadTaxonomyMCPTool(team=self.team, user=self.user)

    async def test_tool_has_correct_name(self):
        self.assertEqual(self.tool.name, "read_taxonomy")

    async def test_read_events_returns_yaml(self):
        content = await self.tool.execute(
            ReadTaxonomyToolArgs(query={"kind": "events"}),
        )

        self.assertIn("events:", content)

    async def test_nonexistent_event_returns_empty_properties(self):
        content = await self.tool.execute(
            ReadTaxonomyToolArgs(query={"kind": "event_properties", "event_name": "nonexistent_event"}),
        )

        self.assertIsNotNone(content)

    async def test_schema_validates_query(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events"}})
        self.assertEqual(validated.query.kind, "events")

        validated = self.tool.args_schema.model_validate(
            {"query": {"kind": "event_properties", "event_name": "$pageview"}}
        )
        self.assertEqual(validated.query.kind, "event_properties")
        assert isinstance(validated.query, ReadEventProperties)
        self.assertEqual(validated.query.event_name, "$pageview")
