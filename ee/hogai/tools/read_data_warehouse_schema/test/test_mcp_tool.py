from posthog.test.base import NonAtomicBaseTest

from ee.hogai.tools.read_data_warehouse_schema.mcp_tool import (
    ReadDataWarehouseSchemaMCPTool,
    ReadDataWarehouseSchemaMCPToolArgs,
)


class TestReadDataWarehouseSchemaMCPTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ReadDataWarehouseSchemaMCPTool(team=self.team, user=self.user)

    async def test_tool_has_correct_name(self):
        self.assertEqual(self.tool.name, "read_data_warehouse_schema")

    async def test_returns_core_table_schemas(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_schema"}),
        )

        self.assertIn("# Core PostHog tables", content)
        for table in ("events", "groups", "persons", "sessions"):
            self.assertIn(f"## Table `{table}`", content)

    async def test_returns_string(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_schema"}),
        )

        self.assertIsInstance(content, str)

    async def test_lists_fields_for_core_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_schema"}),
        )

        self.assertIn("- event (", content)
        self.assertIn("- timestamp (", content)

    async def test_schema_validates_query(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "data_warehouse_schema"}})
        self.assertEqual(validated.query.kind, "data_warehouse_schema")
