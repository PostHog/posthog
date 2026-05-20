from posthog.test.base import NonAtomicBaseTest

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

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
        self.assertIsNone(validated.query.table_names)
        self.assertIsNone(validated.query.include)

    async def test_include_filters_sections(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_schema", "include": ["core"]}),
        )

        self.assertIn("# Core PostHog tables", content)
        self.assertNotIn("# Data warehouse tables", content)
        self.assertNotIn("# PostHog Postgres tables", content)
        self.assertNotIn("# Data warehouse views", content)

    async def test_table_names_filters_core_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["events"], "include": ["core"]},
            ),
        )

        self.assertIn("## Table `events`", content)
        self.assertNotIn("## Table `persons`", content)
        self.assertNotIn("## Table `sessions`", content)

    async def test_views_show_status_and_error(self):
        from posthog.sync import database_sync_to_async

        @database_sync_to_async
        def make_saved_query():
            return DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name="failing_view",
                query={"kind": "HogQLQuery", "query": "SELECT 1 FROM does_not_exist"},
                status=DataWarehouseSavedQuery.Status.FAILED,
                latest_error="Unknown table 'does_not_exist'",
            )

        await make_saved_query()

        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["failing_view"], "include": ["views"]},
            ),
        )

        self.assertIn("failing_view", content)
        self.assertIn("status=Failed", content)
        self.assertIn("Unknown table", content)
