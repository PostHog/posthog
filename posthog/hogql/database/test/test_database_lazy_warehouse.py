import os
import copy
import json
import datetime as dt

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, _build_warehouse_table_definition
from posthog.hogql.database.models import LazyJoin, TableNode
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

N_TABLES = 6

COLUMNS = {
    "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
    "name": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
    "other_id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
}


class TestLazyWarehouseBuild(BaseTest):
    def setUp(self):
        super().setUp()
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
        )
        for i in range(N_TABLES):
            DataWarehouseTable.objects.create(
                name=f"table_{i}",
                format="Parquet",
                team=self.team,
                external_data_source=source,
                credential=credential,
                url_pattern=f"s3://bucket/table_{i}/*",
                columns=COLUMNS,
            )
        # A self-managed table (no source) and a saved-query view.
        DataWarehouseTable.objects.create(
            name="self_managed",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="s3://bucket/self/*",
            columns=COLUMNS,
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"query": "SELECT id FROM table_0"},
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String"}},
        )
        # A join from table_0 to table_1.
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="table_0",
            source_table_key="other_id",
            joining_table_name="table_1",
            joining_table_key="id",
            field_name="joined_table_1",
        )

    def _build(self, *, lazy: bool) -> Database:
        sources = Database._fetch_sources(team=self.team)
        return Database._build_from_sources(sources, lazy_warehouse_tables=lazy)

    @parameterized.expand([("eager", False), ("lazy", True)])
    def test_built_database_is_serializable_and_deepcopyable(self, _name: str, lazy: bool) -> None:
        # Serializable-lazy-join refactor: a built Database holds zero Python callables, so the broad
        # catalog walk (serialize) and a deepcopy must both succeed, and every LazyJoin must be plain
        # data (a resolver tag + JSON-able params) rather than a closure. Pins the closure-crash that
        # previously killed backend shards with no traceback.
        db = self._build(lazy=lazy)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        db.serialize(context)
        copy.deepcopy(db)

        def assert_plain(node: TableNode) -> None:
            if node.table is not None and hasattr(node.table, "fields"):
                for field in node.table.fields.values():
                    if isinstance(field, LazyJoin):
                        assert not callable(getattr(field, "join_function", None)), "LazyJoin carries a closure"
                        json.dumps(field.resolver_params)
            for _field_name, pending, _override in node._pending_fields:
                if isinstance(pending, LazyJoin):
                    json.dumps(pending.resolver_params)
            for child in node.children.values():
                assert_plain(child)

        assert_plain(db.tables)

    @pytest.mark.skipif(
        os.environ.get("HOGQL_LAZY_WAREHOUSE_TABLES") != "1",
        reason="only runs in the lazy-validation suite (HOGQL_LAZY_WAREHOUSE_TABLES=1)",
    )
    def test_test_override_forces_lazy_path(self) -> None:
        # Confirms the TEST-gated env override actually flips _fetch_sources to lazy, so a green
        # validation run can't be a false negative from silently staying on the eager path.
        assert Database._fetch_sources(team=self.team).lazy_warehouse_tables is True

    def _sql(self, db: Database, query: str) -> str:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        printed, _ = prepare_and_print_ast(parse_select(query), context, dialect="clickhouse")
        return printed

    @staticmethod
    def _built_warehouse_count(db: Database) -> int:
        count = 0

        def walk(node: TableNode) -> None:
            nonlocal count
            if node._table_factory is not None and node.table is not None:
                count += 1
            for child in node.children.values():
                walk(child)

        walk(db.tables)
        return count

    @parameterized.expand(
        [
            ("select_star", "SELECT * FROM table_0"),
            ("select_field", "SELECT id, name FROM table_0"),
            ("bare_and_other", "SELECT id FROM table_3"),
            ("self_managed", "SELECT id FROM self_managed"),
            ("view", "SELECT id FROM my_view"),
            ("join", "SELECT id, joined_table_1.id FROM table_0"),
            ("multi_table", "SELECT a.id FROM table_0 AS a CROSS JOIN table_2 AS b"),
        ]
    )
    def test_lazy_resolves_identically_to_eager(self, _name: str, query: str) -> None:
        eager = self._sql(self._build(lazy=False), query)
        lazy = self._sql(self._build(lazy=True), query)
        assert lazy == eager, f"lazy != eager for {query!r}\nlazy:  {lazy}\neager: {eager}"

    def test_eager_builds_every_table(self) -> None:
        db = self._build(lazy=False)
        # All external warehouse tables are drained (bare + dotted nodes per table).
        assert self._built_warehouse_count(db) >= N_TABLES

    def test_lazy_builds_only_referenced_tables(self) -> None:
        db = self._build(lazy=True)
        assert self._built_warehouse_count(db) == 0  # nothing built until a query references it

        self._sql(db, "SELECT id FROM table_0")
        after_one = self._built_warehouse_count(db)
        # table_0 (its bare + dotted node share one object, so 1-2 nodes), far fewer than all tables.
        assert 0 < after_one < N_TABLES, after_one

    @parameterized.expand(
        [
            ("plain", "mytable", ["id", "name"]),
            ("dlt_columns_dropped", "mytable", ["id", "_dlt_id", "_dlt_load_id"]),
            ("asymmetric_dlt_kept", "mytable", ["id", "_dlt_id"]),  # only one of the pair → NOT dropped
            ("ph_debug_dropped", "mytable", ["id", "_ph_debug"]),
            ("partition_key_dropped", "mytable", ["id", PARTITION_KEY]),
            ("properties_id_column", "mytable", ["id", "properties_id"]),  # synthetic `properties` still added
            ("real_properties_column", "mytable", ["id", "properties"]),
            ("redefined_table_replaces_columns", "stripe_creditnote", ["id", "raw_only_id", "another"]),
        ]
    )
    def test_hogql_field_names_matches_built_fields(self, _name: str, table_name: str, column_names: list[str]) -> None:
        # FK wiring checks hogql_field_names() instead of building the table; it must equal the field set
        # the table exposes once BUILT — i.e. _build_warehouse_table_definition (hogql_definition plus the
        # synthetic `properties` virtual table), not just hogql_definition() — or the FK shadow-guard
        # diverges from the eager build.
        source = ExternalDataSource.objects.get(team=self.team, source_id="src")
        cred = DataWarehouseCredential.objects.get(team=self.team)
        table = DataWarehouseTable.objects.create(
            name=table_name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=cred,
            url_pattern=f"s3://bucket/{table_name}/*",
            columns={name: {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"} for name in column_names},
        )
        modifiers = create_default_modifiers_for_team(self.team)
        built, _ = _build_warehouse_table_definition(table, modifiers, now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        built_names = set(built.fields)
        assert table.hogql_field_names() == built_names, f"symmetric diff: {table.hogql_field_names() ^ built_names}"

    def _create_inferred_fk_tables(self) -> None:
        # `fk_table.dim_id` infers a forward FK `dim` on fk_table and a reverse FK `fk_tables` on dim.
        source = ExternalDataSource.objects.get(team=self.team, source_id="src")
        cred = DataWarehouseCredential.objects.get(team=self.team)
        DataWarehouseTable.objects.create(
            name="fk_table",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=cred,
            url_pattern="s3://bucket/fk_table/*",
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
                "dim_id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
            },
        )
        DataWarehouseTable.objects.create(
            name="dim",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=cred,
            url_pattern="s3://bucket/dim/*",
            columns=COLUMNS,
        )

    def test_lazy_bare_name_fk_resolves_identically(self) -> None:
        # Regression: Postgres FK joins are wired onto a table's dotted name, but a query may reference
        # the table by its bare name. The bare and dotted nodes share one pending-fields list, so the
        # forward FK (and the reverse FK on the target) must be visible from either name in lazy mode.
        self._create_inferred_fk_tables()
        for query in ("SELECT dim.id FROM fk_table", "SELECT fk_tables.id FROM dim"):
            eager = self._sql(self._build(lazy=False), query)
            lazy = self._sql(self._build(lazy=True), query)
            assert lazy == eager, f"lazy != eager for {query!r}\nlazy:  {lazy}\neager: {eager}"

    def test_lazy_inference_does_not_build_target(self) -> None:
        # FK inference resolves a target's columns from metadata, so wiring an inferred FK must not
        # build the target table during the (lazy) build phase.
        self._create_inferred_fk_tables()
        db = self._build(lazy=True)
        dim = db.get_table_node("postgres.dim")
        assert dim._table_factory is not None and dim.table is None  # registered but not built
        assert self._built_warehouse_count(db) == 0

    @parameterized.expand([("eager", False), ("lazy", True)])
    def test_fk_does_not_bridge_distinct_sources(self, _name: str, lazy: bool) -> None:
        # Cross-source isolation: a `_id` column must not infer a FK to a same-named table in a
        # *different* external source (a different namespace). Holds in both eager and lazy builds.
        cred = DataWarehouseCredential.objects.get(team=self.team)
        postgres_source = ExternalDataSource.objects.get(team=self.team, source_id="src")
        other_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="other",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.MYSQL,
        )
        DataWarehouseTable.objects.create(
            name="orders",
            format="Parquet",
            team=self.team,
            external_data_source=postgres_source,
            credential=cred,
            url_pattern="s3://bucket/orders/*",
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
                "customer_id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
            },
        )
        # Same-named target, but in a different source/namespace (mysql.customers, not postgres.customers).
        DataWarehouseTable.objects.create(
            name="customers",
            format="Parquet",
            team=self.team,
            external_data_source=other_source,
            credential=cred,
            url_pattern="s3://bucket/customers/*",
            columns=COLUMNS,
        )
        orders = self._build(lazy=lazy).get_table("orders")
        assert "customer" not in orders.fields  # no cross-source FK was wired

    def _view_node(self, db: Database) -> TableNode:
        node = db.tables.children["my_view"]
        assert node._table_factory is not None  # registered as a deferred stub, not an eager build
        return node

    def test_lazy_defers_view_until_referenced(self) -> None:
        db = self._build(lazy=True)
        assert self._view_node(db).table is None  # view not built at build time

        self._sql(db, "SELECT id FROM table_0")
        assert self._view_node(db).table is None  # nor when an unrelated table is queried

        self._sql(db, "SELECT id FROM my_view")
        assert self._view_node(db).table is not None  # built only once a query references it
