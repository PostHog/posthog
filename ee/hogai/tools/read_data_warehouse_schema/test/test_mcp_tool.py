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

    async def test_returns_only_requested_table_when_table_names_provided(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["events"]},
            ),
        )

        self.assertIn("# Requested tables", content)
        self.assertIn("## Table `events` (core)", content)
        self.assertNotIn("# Core PostHog tables", content)
        self.assertNotIn("# Data warehouse tables", content)
        self.assertNotIn("# PostHog Postgres tables", content)
        self.assertNotIn("# Data warehouse views", content)

    async def test_returns_multiple_requested_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["events", "persons"]},
            ),
        )

        self.assertIn("## Table `events` (core)", content)
        self.assertIn("## Table `persons` (core)", content)
        self.assertNotIn("# Core PostHog tables", content)
        self.assertNotIn("# Data warehouse tables", content)

    async def test_unknown_table_returns_not_found_section(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["does_not_exist"]},
            ),
        )

        self.assertIn("## Not found", content)
        self.assertIn("`does_not_exist`", content)
        self.assertIn("available tables include:", content)

    async def test_mixed_known_and_unknown_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["events", "does_not_exist"]},
            ),
        )

        self.assertIn("## Table `events` (core)", content)
        self.assertIn("## Not found", content)
        self.assertIn("`does_not_exist`", content)

    async def test_empty_table_names_falls_back_to_full_catalog(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": []},
            ),
        )

        self.assertIn("# Core PostHog tables", content)
        for table in ("events", "groups", "persons", "sessions"):
            self.assertIn(f"## Table `{table}`", content)
        self.assertNotIn("# Requested tables", content)

    async def test_omitted_table_names_unchanged_behavior(self):
        with_default = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_schema"}),
        )
        with_none = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": None},
            ),
        )

        self.assertEqual(with_default, with_none)

    async def test_schema_validates_query_with_table_names(self):
        validated = self.tool.args_schema.model_validate(
            {"query": {"kind": "data_warehouse_schema", "table_names": ["events", "stripe_charges"]}}
        )
        self.assertEqual(validated.query.table_names, ["events", "stripe_charges"])

    async def test_persons_db_tables_excluded(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["group_type_mappings"]},
            ),
        )

        self.assertIn("## Not found", content)
        self.assertIn("`group_type_mappings`", content)

    async def test_deduplicates_requested_names(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_schema", "table_names": ["events", "events"]},
            ),
        )

        self.assertEqual(content.count("## Table `events` (core)"), 1)
