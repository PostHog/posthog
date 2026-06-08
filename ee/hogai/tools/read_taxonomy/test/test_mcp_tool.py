from posthog.test.base import NonAtomicBaseTest

from ee.hogai.tools.read_taxonomy.core import ReadEventProperties, ReadEvents, ReadTaxonomyToolArgs
from ee.hogai.tools.read_taxonomy.mcp_tool import ReadTaxonomyMCPTool


class TestReadTaxonomyMCPTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ReadTaxonomyMCPTool(team=self.team, user=self.user)

    async def test_tool_has_correct_name(self):
        assert self.tool.name == "read_taxonomy"

    async def test_read_events_returns_yaml(self):
        content = await self.tool.execute(
            ReadTaxonomyToolArgs(query={"kind": "events"}),
        )

        assert "events:" in content

    async def test_nonexistent_event_returns_empty_properties(self):
        content = await self.tool.execute(
            ReadTaxonomyToolArgs(query={"kind": "event_properties", "event_name": "nonexistent_event"}),
        )

        assert content is not None

    async def test_schema_validates_query(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events"}})
        assert validated.query.kind == "events"

        validated = self.tool.args_schema.model_validate(
            {"query": {"kind": "event_properties", "event_name": "$pageview"}}
        )
        assert validated.query.kind == "event_properties"
        assert isinstance(validated.query, ReadEventProperties)
        assert validated.query.event_name == "$pageview"

    async def test_schema_validates_events_with_pagination(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events", "limit": 100, "offset": 50}})
        assert validated.query.kind == "events"
        assert isinstance(validated.query, ReadEvents)
        assert validated.query.limit == 100
        assert validated.query.offset == 50

    async def test_schema_validates_events_default_pagination(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events"}})
        assert isinstance(validated.query, ReadEvents)
        assert validated.query.limit == 500
        assert validated.query.offset == 0
