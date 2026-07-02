from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.information_schema import (
    _bound_table_names,
    _pushdown_table_filter,
    _warehouse_metadata,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.data_modeling.backend.facade.models import (
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable
from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics


def _field(name: str) -> ast.Field:
    return ast.Field(chain=[name])


def _eq(field: str, value: str) -> ast.CompareOperation:
    return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=_field(field), right=ast.Constant(value=value))


def _in(field: str, values: list[str]) -> ast.CompareOperation:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=_field(field),
        right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values]),
    )


class TestInformationSchemaPushdown(APIBaseTest):
    @parameterized.expand(
        [
            ("eq", _eq("table_name", "events"), {"events"}),
            # The resolver wraps the column in an Alias; matching must see through it.
            (
                "aliased_field",
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Alias(alias="table_name", expr=_field("table_name")),
                    right=ast.Constant(value="events"),
                ),
                {"events"},
            ),
            (
                "flipped_eq",
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq, left=ast.Constant(value="events"), right=_field("table_name")
                ),
                {"events"},
            ),
            ("in_list", _in("table_name", ["a", "b"]), {"a", "b"}),
            # AND with an unrelated/unbounded conjunct keeps the bound from the conjunct we understand.
            ("and_with_unrelated", ast.And(exprs=[_eq("table_name", "events"), _eq("data_type", "JSON")]), {"events"}),
            # AND of two bounds intersects (here to an unsatisfiable empty set).
            ("and_intersects", ast.And(exprs=[_eq("table_name", "a"), _eq("table_name", "b")]), set()),
            # OR where every branch is bounded unions them.
            ("or_all_bounded", ast.Or(exprs=[_eq("table_name", "a"), _in("table_name", ["b", "c"])]), {"a", "b", "c"}),
            # OR with an unbounded branch can match any table → must widen to None (never drop rows).
            ("or_one_unbounded", ast.Or(exprs=[_eq("table_name", "a"), _eq("data_type", "JSON")]), None),
            # Negation and other ops we can't safely bound → None.
            (
                "not_eq",
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq, left=_field("table_name"), right=ast.Constant(value="x")
                ),
                None,
            ),
            ("unrelated_column", _eq("data_type", "JSON"), None),
            (
                "no_constant",
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq, left=_field("table_name"), right=_field("table_schema")
                ),
                None,
            ),
        ]
    )
    def test_bound_table_names(self, _name: str, where: ast.Expr, expected: set[str] | None) -> None:
        assert _bound_table_names(where, "table_name") == expected

    def test_pushdown_skipped_when_query_has_a_join(self) -> None:
        # With a join, a bare `table_name` could resolve to either relation, so a wrong bound might
        # drop rows — pushdown must bail out (None) and emit everything instead.
        joined = ast.SelectQuery(
            select=[_field("table_name")],
            select_from=ast.JoinExpr(table=_field("columns"), next_join=ast.JoinExpr(table=_field("tables"))),
            where=_eq("table_name", "events"),
        )
        assert _pushdown_table_filter(joined, "table_name") is None

    def test_pushdown_returns_frozenset_for_simple_query(self) -> None:
        simple = ast.SelectQuery(
            select=[_field("table_name")],
            select_from=ast.JoinExpr(table=_field("columns")),
            where=_eq("table_name", "events"),
        )
        assert _pushdown_table_filter(simple, "table_name") == frozenset({"events"})


class TestWarehouseMetadata(APIBaseTest):
    def _table(
        self, name: str, row_count: int | None, *, deleted: bool = False, team: Team | None = None
    ) -> DataWarehouseTable:
        team = team or self.team
        credential = DataWarehouseCredential.objects.create(access_key="x", access_secret="x", team=team)
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            row_count=row_count,
            deleted=deleted,
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def test_soft_deleted_duplicate_does_not_clobber_live_row_count(self):
        # Re-synced tables leave soft-deleted duplicates sharing the name; the live row_count must win
        # rather than being clobbered by a dead row's stale value (which is what `.objects` returned).
        self._table("orders", 100)
        self._table("orders", 5, deleted=True)
        row_counts, _view_row_counts, _column_stats = _warehouse_metadata(self.team.id)
        assert row_counts["orders"] == 100

    def test_view_row_count_comes_from_the_backing_table(self):
        backing = self._table("orders_view_backing", 42)
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders_view", query={"query": "SELECT 1"}, columns={}, table=backing
        )
        _row_counts, view_row_counts, _column_stats = _warehouse_metadata(self.team.id)
        assert view_row_counts["orders_view"] == 42

    def test_metadata_does_not_leak_other_teams_row_counts(self):
        # `DataWarehouseTable` is not team-scoped, so the query must filter team_id explicitly — a
        # same-named table in another team must not surface (or clobber) this team's count.
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._table("shared", 999, team=other_team)
        self._table("shared", 7)
        row_counts, _view_row_counts, _column_stats = _warehouse_metadata(self.team.id)
        assert row_counts["shared"] == 7


class TestInformationSchema(ClickhouseTestMixin, APIBaseTest):
    def _context(self, db: Database) -> HogQLContext:
        return HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)

    def test_information_schema_tables_are_registered_under_system(self):
        db = Database.create_for(team=self.team)
        names = db.get_system_table_names()
        for table in ["tables", "columns", "relationships", "data_types"]:
            assert f"system.information_schema.{table}" in names

    def test_select_compiles_to_an_external_table_reference(self):
        # Rows are sent out-of-band as a ClickHouse external data table, so the printed SQL references
        # the external table by name and never inlines the catalog as constants.
        db = Database.create_for(team=self.team)
        context = self._context(db)
        sql = "SELECT table_name, table_type, table_schema, description FROM system.information_schema.tables"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        assert "arrayJoin" not in query
        assert "__ph_information_schema_tables_" in query
        # The matching external data was registered on the context for the executor to send.
        registered = list(context.external_tables.values())
        assert len(registered) == 1
        assert registered[0]["name"] in query
        assert any(name == "table_name" for name, _ in registered[0]["structure"])
        assert any(row["table_name"] == "events" for row in registered[0]["data"])

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

    @parameterized.expand(
        [
            ("person_id", "String"),
            ("event_issue_id", "UUID"),
            ("issue_first_seen", "DateTime"),
            ("$virt_is_bot", "Boolean"),
        ]
    )
    def test_expression_columns_resolve_to_their_value_type(self, column_name: str, expected_type: str):
        # Expression columns must report the type they evaluate to (like hogql autocomplete), not the
        # generic "Expression" — otherwise the catalog is useless for picking a cast/comparison.
        response = execute_hogql_query(
            f"SELECT data_type, field_kind FROM system.information_schema.columns "
            f"WHERE table_name = 'events' AND column_name = '{column_name}'",
            team=self.team,
        )
        results = response.results or []
        assert len(results) == 1
        assert results[0][1] == "expression"
        assert results[0][0] == expected_type

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

    def _create_warehouse_table(self, name: str = "stripe_charges", column: str = "id") -> DataWarehouseTable:
        credentials = DataWarehouseCredential.objects.create(access_key="x", access_secret="x", team=self.team)
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            row_count=42,
            columns={column: {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def _create_saved_query_view(
        self, name: str = "revenue_view", *, table: DataWarehouseTable | None = None, is_materialized: bool = False
    ) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"query": "SELECT order_id, amount FROM events"},
            columns={
                "order_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "amount": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
            },
            table=table,
            is_materialized=is_materialized,
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

    def test_warehouse_column_statistics_are_merged(self):
        # Per-column profiling stats are surfaced on information_schema.columns for warehouse tables,
        # keyed by table id + column (like descriptions). A warehouse column without stats stays NULL.
        credentials = DataWarehouseCredential.objects.create(access_key="x", access_secret="x", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="stripe_charges",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            row_count=42,
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
                "amount": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
            },
        )
        with team_scope(self.team.id, canonical=True):
            WarehouseColumnStatistics.objects.create(
                team=self.team,
                table=table,
                column_name="id",
                null_fraction=0.25,
                min_value="ch_001",
                max_value="ch_999",
                has_min_max=True,
            )

        rows = (
            execute_hogql_query(
                """
                SELECT column_name, null_fraction, min_value, max_value
                FROM system.information_schema.columns
                WHERE table_name = 'stripe_charges'
                ORDER BY column_name
                """,
                team=self.team,
            ).results
            or []
        )
        by_column = {row[0]: list(row[1:]) for row in rows}
        assert by_column["id"] == [0.25, "ch_001", "ch_999"]
        # Profiled stats absent for this column → all NULL.
        assert by_column["amount"] == [None, None, None]

    def test_saved_query_view_appears_in_tables(self):
        # A saved-query view must surface in the catalog as a discoverable table so PostHog AI can find
        # it. Regression guard for the whole semantic-layer effort: if views stop being enumerated (or are
        # misclassified as posthog/data_warehouse), descriptions wired onto them later never reach the AI.
        self._create_saved_query_view(name="revenue_view")
        response = execute_hogql_query(
            "SELECT table_type, table_schema FROM system.information_schema.tables WHERE table_name = 'revenue_view'",
            team=self.team,
        )
        results = response.results or []
        assert len(results) == 1
        assert results[0][0] == "view"
        assert results[0][1] == "views"

    def test_saved_query_view_columns_appear_with_types(self):
        # The view's columns (built from the model's `columns` JSONField via `hogql_definition`) must be
        # enumerated with their HogQL types. Guards both the field enumeration and the JSONField→HogQL
        # type mapping for views.
        self._create_saved_query_view(name="revenue_view")
        response = execute_hogql_query(
            """
            SELECT column_name, data_type FROM system.information_schema.columns
            WHERE table_name = 'revenue_view'
            """,
            team=self.team,
        )
        columns = {row[0]: row[1] for row in response.results or []}
        assert columns["order_id"] == "String"
        assert columns["amount"] == "Integer"

    def test_saved_query_view_descriptions_are_merged_from_annotations(self):
        # View- and column-level descriptions stored as DataWarehouseSavedQueryColumnAnnotation must
        # surface in the catalog so PostHog AI can read them. Guards the metadata loader plus the
        # `table_type == "view"` resolution branch: a regression (loader dropped, wrong key, or branch
        # gated on the wrong table_type) makes descriptions silently vanish from information_schema.
        view = self._create_saved_query_view(name="revenue_view")
        with team_scope(self.team.id, canonical=True):
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=view,
                column_name="",
                description="Revenue per order, one row per completed order.",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.USER_EDITED,
            )
            DataWarehouseSavedQueryColumnAnnotation.objects.create(
                team=self.team,
                saved_query=view,
                column_name="amount",
                description="Order revenue in cents.",
                description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.AI_GENERATED,
            )

        table_rows = (
            execute_hogql_query(
                "SELECT description FROM system.information_schema.tables WHERE table_name = 'revenue_view'",
                team=self.team,
            ).results
            or []
        )
        assert len(table_rows) == 1
        assert table_rows[0][0] == "Revenue per order, one row per completed order."

        column_rows = (
            execute_hogql_query(
                "SELECT column_name, description FROM system.information_schema.columns WHERE table_name = 'revenue_view'",
                team=self.team,
            ).results
            or []
        )
        by_column = {row[0]: row[1] for row in column_rows}
        assert by_column["amount"] == "Order revenue in cents."
        # An unannotated column stays NULL rather than borrowing another column's description.
        assert by_column["order_id"] is None

    def test_materialized_saved_query_view_reports_backing_table_row_count(self):
        # A materialized view stays classified as a view but carries the row count of its backing table.
        # Exercises the `table_type == "view"` branch of row-count resolution end-to-end (the unit test on
        # `_warehouse_metadata` stops at the metadata dict; this proves it reaches the catalog row).
        backing = self._create_warehouse_table(name="revenue_view_backing")
        self._create_saved_query_view(name="revenue_view_materialized", table=backing, is_materialized=True)
        response = execute_hogql_query(
            "SELECT table_type, row_count FROM system.information_schema.tables "
            "WHERE table_name = 'revenue_view_materialized'",
            team=self.team,
        )
        results = response.results or []
        assert len(results) == 1
        assert results[0][0] == "view"
        assert results[0][1] == 42

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

    def test_pushdown_sends_only_the_filtered_table(self):
        # A `WHERE table_name = '…'` query must only ship that table's rows in the external data,
        # never the whole catalog — that's what keeps the out-of-band payload (and the work) small.
        self._create_warehouse_table(name="stripe_charges", column="charge_id")
        self._create_warehouse_table(name="stripe_refunds", column="refund_id")
        db = Database.create_for(team=self.team)
        context = self._context(db)
        prepare_and_print_ast(
            parse_select(
                "SELECT column_name FROM system.information_schema.columns WHERE table_name = 'stripe_charges'"
            ),
            context,
            dialect="clickhouse",
        )
        rows = next(iter(context.external_tables.values()))["data"]
        shipped_tables = {row["table_name"] for row in rows}
        assert shipped_tables == {"stripe_charges"}

    def test_columns_in_filter_returns_only_listed_tables(self):
        for name, column in (("orders", "order_id"), ("refunds", "refund_id"), ("customers", "customer_id")):
            self._create_warehouse_table(name=name, column=column)
        response = execute_hogql_query(
            """
            SELECT DISTINCT table_name FROM system.information_schema.columns
            WHERE table_name IN ('orders', 'refunds')
            """,
            team=self.team,
        )
        names = {row[0] for row in response.results or []}
        assert names == {"orders", "refunds"}

    def test_disjunction_with_unbounded_branch_does_not_drop_rows(self):
        # An OR where one branch isn't a table_name bound (here a data_type predicate) can match rows
        # from tables not named in the query, so pushdown must widen to "emit everything" rather than
        # bound to the named table — otherwise we'd silently drop matching rows.
        response = execute_hogql_query(
            """
            SELECT DISTINCT table_name FROM system.information_schema.columns
            WHERE table_name = 'events' OR data_type = 'JSON'
            """,
            team=self.team,
        )
        names = {row[0] for row in response.results or []}
        # `persons` has JSON columns but isn't named in the WHERE — it must still come through.
        assert "events" in names
        assert "persons" in names

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
