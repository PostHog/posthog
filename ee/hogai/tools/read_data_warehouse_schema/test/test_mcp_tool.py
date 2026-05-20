from types import SimpleNamespace

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

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

    async def test_catalog_returns_core_table_schemas(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_catalog"}),
        )

        self.assertIn("# Core PostHog tables", content)
        for table in ("events", "groups", "persons", "sessions"):
            self.assertIn(f"## Table `{table}`", content)

    async def test_catalog_returns_string(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_catalog"}),
        )

        self.assertIsInstance(content, str)

    async def test_catalog_lists_fields_for_core_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(query={"kind": "data_warehouse_catalog"}),
        )

        self.assertIn("- event (", content)
        self.assertIn("- timestamp (", content)

    async def test_schema_validates_catalog_query(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "data_warehouse_catalog"}})
        self.assertEqual(validated.query.kind, "data_warehouse_catalog")

    async def test_tables_kind_returns_only_requested_table(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_tables", "table_names": ["events"]},
            ),
        )

        self.assertIn("# Requested tables", content)
        self.assertIn("## Table `events` (core)", content)
        self.assertNotIn("# Core PostHog tables", content)
        self.assertNotIn("# Data warehouse tables", content)
        self.assertNotIn("# PostHog Postgres tables", content)
        self.assertNotIn("# Data warehouse views", content)

    async def test_tables_kind_returns_multiple_requested_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_tables", "table_names": ["events", "persons"]},
            ),
        )

        self.assertIn("## Table `events` (core)", content)
        self.assertIn("## Table `persons` (core)", content)
        self.assertNotIn("# Core PostHog tables", content)
        self.assertNotIn("# Data warehouse tables", content)

    async def test_tables_kind_unknown_table_returns_not_found_section(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_tables", "table_names": ["does_not_exist"]},
            ),
        )

        self.assertIn("## Not found", content)
        self.assertIn("`does_not_exist`", content)
        self.assertIn("available tables include:", content)

    async def test_tables_kind_mixed_known_and_unknown_tables(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_tables", "table_names": ["events", "does_not_exist"]},
            ),
        )

        self.assertIn("## Table `events` (core)", content)
        self.assertIn("## Not found", content)
        self.assertIn("`does_not_exist`", content)

    async def test_tables_kind_rejects_empty_table_names(self):
        # min_length=1 — the tables kind without any names would be ambiguous with
        # the catalog kind, so Pydantic must reject it.
        with self.assertRaises(Exception):
            self.tool.args_schema.model_validate({"query": {"kind": "data_warehouse_tables", "table_names": []}})

    async def test_schema_validates_tables_query(self):
        validated = self.tool.args_schema.model_validate(
            {"query": {"kind": "data_warehouse_tables", "table_names": ["events", "stripe_charges"]}}
        )
        self.assertEqual(validated.query.kind, "data_warehouse_tables")
        self.assertEqual(validated.query.table_names, ["events", "stripe_charges"])

    async def test_tables_kind_persons_db_tables_excluded(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_tables", "table_names": ["group_type_mappings"]},
            ),
        )

        self.assertIn("## Not found", content)
        self.assertIn("`group_type_mappings`", content)

    async def test_tables_kind_deduplicates_requested_names(self):
        content = await self.tool.execute(
            ReadDataWarehouseSchemaMCPToolArgs(
                query={"kind": "data_warehouse_tables", "table_names": ["events", "events"]},
            ),
        )

        self.assertEqual(content.count("## Table `events` (core)"), 1)

    def test_resolve_warehouse_canonical_maps_underscore_alias_to_dotted_form(self):
        warehouse = {"hubspot.companies", "hubspot_companies"}
        self.assertEqual(
            ReadDataWarehouseSchemaMCPTool._resolve_warehouse_canonical("hubspot_companies", warehouse),
            "hubspot.companies",
        )

    def test_resolve_warehouse_canonical_handles_multi_underscore_suffix(self):
        warehouse = {"intercom.activity_logs", "intercom_activity_logs"}
        self.assertEqual(
            ReadDataWarehouseSchemaMCPTool._resolve_warehouse_canonical("intercom_activity_logs", warehouse),
            "intercom.activity_logs",
        )

    def test_resolve_warehouse_canonical_returns_none_when_already_dotted(self):
        warehouse = {"hubspot.companies"}
        self.assertIsNone(ReadDataWarehouseSchemaMCPTool._resolve_warehouse_canonical("hubspot.companies", warehouse))

    def test_resolve_warehouse_canonical_returns_none_when_no_match(self):
        warehouse = {"hubspot.companies"}
        self.assertIsNone(ReadDataWarehouseSchemaMCPTool._resolve_warehouse_canonical("unrelated_table", warehouse))

    async def test_warehouse_underscore_alias_renders_via_canonical_form(self):
        # Simulates the real catalog where get_warehouse_table_names() returns both
        # the dotted canonical name and an underscored alias, but serialize() only
        # honors the dotted form. Asking for the alias should still render columns.
        fake_table = SimpleNamespace(
            fields={
                "id": SimpleNamespace(name="id", type="string"),
                "name": SimpleNamespace(name="name", type="string"),
            }
        )
        fake_database = SimpleNamespace(
            get_warehouse_table_names=lambda: ["hubspot.companies", "hubspot_companies"],
            get_system_table_names=lambda: [],
            get_view_names=lambda: [],
            serialize=lambda ctx, include_only: (
                {"hubspot.companies": fake_table} if "hubspot.companies" in include_only else {}
            ),
        )
        with (
            patch.object(self.tool, "_get_database", return_value=fake_database),
            patch.object(self.tool, "_get_default_hogql_context", return_value=object()),
        ):
            content = await self.tool.execute(
                ReadDataWarehouseSchemaMCPToolArgs(
                    query={"kind": "data_warehouse_tables", "table_names": ["hubspot_companies"]},
                ),
            )

        self.assertIn("## Table `hubspot_companies` (data warehouse)", content)
        self.assertIn("- id (string)", content)
        self.assertNotIn("## Not found", content)

    async def test_known_warehouse_name_falls_back_to_not_found_when_serialize_drops_it(self):
        # If a name is in get_warehouse_table_names() but serialize() still doesn't
        # return it (no resolvable canonical form), it must land in `## Not found`
        # rather than disappearing silently from the response.
        fake_database = SimpleNamespace(
            get_warehouse_table_names=lambda: ["orphan_table"],
            get_system_table_names=lambda: [],
            get_view_names=lambda: [],
            serialize=lambda ctx, include_only: {},
        )
        with (
            patch.object(self.tool, "_get_database", return_value=fake_database),
            patch.object(self.tool, "_get_default_hogql_context", return_value=object()),
        ):
            content = await self.tool.execute(
                ReadDataWarehouseSchemaMCPToolArgs(
                    query={"kind": "data_warehouse_tables", "table_names": ["orphan_table"]},
                ),
            )

        self.assertIn("## Not found", content)
        self.assertIn("`orphan_table`", content)
        self.assertNotIn("## Table `orphan_table`", content)
