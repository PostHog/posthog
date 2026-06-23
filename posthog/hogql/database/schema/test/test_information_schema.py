from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.scoping import team_scope

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestInformationSchema(ClickhouseTestMixin, APIBaseTest):
    def _context(self, db: Database) -> HogQLContext:
        return HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)

    def test_information_schema_tables_are_registered_under_system(self):
        db = Database.create_for(team=self.team)
        names = db.get_system_table_names()
        for table in ["tables", "columns", "relationships", "data_types"]:
            assert f"system.information_schema.{table}" in names

    def test_select_from_information_schema_tables_compiles(self):
        db = Database.create_for(team=self.team)
        sql = "SELECT table_name, table_type, table_schema, description FROM system.information_schema.tables"
        query, _ = prepare_and_print_ast(parse_select(sql), self._context(db), dialect="clickhouse")
        assert "arrayJoin" in query

    def test_tables_lists_builtin_and_system_tables(self):
        response = execute_hogql_query(
            "SELECT table_name, table_type FROM system.information_schema.tables", team=self.team
        )
        rows = {row[0]: row[1] for row in response.results or []}
        assert rows.get("events") == "posthog"
        assert rows.get("persons") == "posthog"
        assert rows.get("sessions") == "posthog"
        # `cohorts` is an unscoped system table, so it is always visible
        assert rows.get("system.cohorts") == "system"
        # information_schema is self-describing
        assert rows.get("system.information_schema.columns") == "information_schema"

    def test_access_scoped_system_tables_are_filtered(self):
        # Access-scoped system tables the caller can't reach must not leak into the catalog,
        # while unscoped ones remain visible — mirroring the SQL editor's access decision.
        response = execute_hogql_query(
            "SELECT table_name FROM system.information_schema.tables WHERE table_schema = 'system'",
            team=self.team,
        )
        names = {row[0] for row in response.results or []}
        assert "system.cohorts" in names
        assert "system.feature_flags" not in names

    def test_columns_lists_event_columns_with_types(self):
        response = execute_hogql_query(
            """
            SELECT column_name, data_type, is_nullable, is_array, field_kind
            FROM system.information_schema.columns
            WHERE table_name = 'events'
            """,
            team=self.team,
        )
        columns = {row[0]: (row[1], row[2], row[3], row[4]) for row in response.results or []}
        assert columns["uuid"][0] == "String"
        assert columns["timestamp"][0] == "DateTime"
        assert columns["properties"][0] == "JSON"
        # `event` is a non-nullable string column
        assert columns["event"][0] == "String"

    def test_columns_surface_seeded_descriptions(self):
        response = execute_hogql_query(
            """
            SELECT column_name, description
            FROM system.information_schema.columns
            WHERE table_name = 'events' AND column_name = 'distinct_id'
            """,
            team=self.team,
        )
        results = response.results or []
        assert len(results) == 1
        assert results[0][1] is not None and len(results[0][1]) > 0

    def test_relationships_lists_event_lazy_joins(self):
        response = execute_hogql_query(
            """
            SELECT source_table, source_column, target_table, relationship_kind
            FROM system.information_schema.relationships
            WHERE source_table = 'events'
            """,
            team=self.team,
        )
        kinds = {(row[1], row[3]) for row in response.results or []}
        # events.pdi is a lazy join; events.person is a field traverser
        assert any(kind == "lazy_join" for _, kind in kinds)
        assert any(kind == "field_traverser" for _, kind in kinds)

    def test_data_types_is_static_reference(self):
        response = execute_hogql_query("SELECT type_name FROM system.information_schema.data_types", team=self.team)
        type_names = {row[0] for row in response.results or []}
        assert {"String", "DateTime", "JSON", "Integer", "Boolean"}.issubset(type_names)

    def _create_warehouse_table(self) -> DataWarehouseTable:
        credentials = DataWarehouseCredential.objects.create(access_key="x", access_secret="x", team=self.team)
        return DataWarehouseTable.objects.create(
            name="stripe_charges",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            row_count=42,
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def test_warehouse_tables_appear_with_row_count(self):
        self._create_warehouse_table()
        response = execute_hogql_query(
            "SELECT table_type, row_count FROM system.information_schema.tables WHERE table_name = 'stripe_charges'",
            team=self.team,
        )
        results = response.results or []
        assert len(results) == 1
        assert results[0][0] == "data_warehouse"
        assert results[0][1] == 42

    def test_warehouse_descriptions_are_merged_from_annotations(self):
        table = self._create_warehouse_table()
        with team_scope(self.team.id, canonical=True):
            WarehouseColumnAnnotation.objects.create(
                team=self.team,
                table=table,
                column_name="",
                description="All Stripe charges synced into the warehouse.",
                description_source=WarehouseColumnAnnotation.DescriptionSource.USER_EDITED,
            )
            WarehouseColumnAnnotation.objects.create(
                team=self.team,
                table=table,
                column_name="id",
                description="Stripe charge identifier (ch_...).",
                description_source=WarehouseColumnAnnotation.DescriptionSource.USER_EDITED,
            )

        tables = (
            execute_hogql_query(
                "SELECT description FROM system.information_schema.tables WHERE table_name = 'stripe_charges'",
                team=self.team,
            ).results
            or []
        )
        assert tables[0][0] == "All Stripe charges synced into the warehouse."

        columns = (
            execute_hogql_query(
                """
            SELECT description FROM system.information_schema.columns
            WHERE table_name = 'stripe_charges' AND column_name = 'id'
            """,
                team=self.team,
            ).results
            or []
        )
        assert columns[0][0] == "Stripe charge identifier (ch_...)."

    def test_ordinal_positions_are_unique_within_a_table(self):
        # `events` exposes nested virtual-table columns (e.g. `group_0.*`); their ordinals must
        # continue the parent table's numbering rather than restart at 1 and collide.
        response = execute_hogql_query(
            """
            SELECT column_name, ordinal_position
            FROM system.information_schema.columns
            WHERE table_name = 'events'
            """,
            team=self.team,
        )
        results = response.results or []
        ordinals = [row[1] for row in results]
        assert len(ordinals) == len(set(ordinals))
        # Numbering is contiguous from 1, so the highest ordinal equals the column count.
        assert sorted(ordinals) == list(range(1, len(ordinals) + 1))
        # Sanity check that at least one nested virtual-table column was surfaced.
        assert any("." in row[0] for row in results)

    def test_columns_filter_and_join_against_tables(self):
        # Proves the virtual tables behave like real relations: WHERE + JOIN both work.
        response = execute_hogql_query(
            """
            SELECT c.table_name, count() AS column_count
            FROM system.information_schema.columns AS c
            JOIN system.information_schema.tables AS t ON c.table_name = t.table_name
            WHERE t.table_type = 'posthog' AND c.table_name = 'persons'
            GROUP BY c.table_name
            """,
            team=self.team,
        )
        results = response.results or []
        assert len(results) == 1
        assert results[0][0] == "persons"
        assert results[0][1] > 0
