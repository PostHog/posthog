from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable


def _cols(*names: str) -> dict[str, dict[str, str | bool]]:
    hogql = {
        "id": "IntegerDatabaseField",
        "user_id": "IntegerDatabaseField",
        "order_id": "IntegerDatabaseField",
        "amount": "FloatDatabaseField",
    }
    clickhouse = {"IntegerDatabaseField": "Int64", "FloatDatabaseField": "Float64", "StringDatabaseField": "String"}
    out: dict[str, dict[str, str | bool]] = {}
    for name in names:
        hogql_type = hogql.get(name, "StringDatabaseField")
        out[name] = {"clickhouse": clickhouse[hogql_type], "hogql": hogql_type, "valid": True}
    return out


class TestLazyWarehouseEquivalence(BaseTest):
    """Lazy and eager warehouse builds must produce identical resolved SQL and catalogs."""

    def setUp(self) -> None:
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="key", access_secret="secret"
        )
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src",
            connection_id="conn",
            source_type=ExternalDataSourceType.POSTGRES,
            status="Completed",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        )

        def make_table(name: str, columns: dict, *, foreign_keys: list[dict] | None = None) -> DataWarehouseTable:
            table = DataWarehouseTable.objects.create(
                team=self.team,
                name=name,
                format=DataWarehouseTable.TableFormat.Parquet,
                url_pattern=f"s3://bucket/{name}/*.parquet",
                credential=self.credential,
                external_data_source=self.source,
                columns=columns,
            )
            ExternalDataSchema.objects.create(
                team=self.team,
                source=self.source,
                name=name,
                table=table,
                should_sync=True,
                sync_type_config={"schema_metadata": {"foreign_keys": foreign_keys}} if foreign_keys else {},
            )
            return table

        make_table("users", _cols("id", "name", "email"))
        make_table("orders", _cols("id", "user_id", "amount"))  # inferred FK orders.user -> users
        make_table(
            "line_items",
            _cols("id", "order_id", "sku"),
            foreign_keys=[{"column": "order_id", "target_table": "orders", "target_column": "id"}],  # explicit FK
        )
        # Self-managed table (no external source) to cover that branch.
        DataWarehouseTable.objects.create(
            team=self.team,
            name="local_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://bucket/local/*.parquet",
            credential=self.credential,
            columns=_cols("id", "label"),
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="postgres.orders",
            source_table_key="user_id",
            joining_table_name="postgres.users",
            joining_table_key="id",
            field_name="user_join",
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="id",
            joining_table_name="postgres.orders",
            joining_table_key="user_id",
            field_name="orders_join",
        )

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"query": "SELECT 1 AS x"},
            columns=_cols("x"),
        )

    def _build(self, *, lazy: bool) -> Database:
        return Database.create_for(team=self.team, lazy_warehouse_tables=lazy)

    def _print(self, database: Database, sql: str) -> str:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=database,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        printed, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        return printed

    def _assert_same_sql(self, sql: str) -> None:
        # Fresh databases per query so materialization state can't leak between assertions.
        eager = self._print(self._build(lazy=False), sql)
        lazy = self._print(self._build(lazy=True), sql)
        self.assertEqual(eager, lazy, f"eager vs lazy SQL diverged for: {sql}")

    def test_catalog_names_match(self) -> None:
        eager = self._build(lazy=False)
        lazy = self._build(lazy=True)
        self.assertEqual(sorted(eager.get_warehouse_table_names()), sorted(lazy.get_warehouse_table_names()))
        self.assertEqual(sorted(eager.get_view_names()), sorted(lazy.get_view_names()))
        self.assertEqual(sorted(eager.get_all_table_names()), sorted(lazy.get_all_table_names()))

    def test_select_star_matches(self) -> None:
        for table in ["postgres.users", "postgres.orders", "postgres.line_items", "local_table", "my_view"]:
            self._assert_same_sql(f"SELECT * FROM {table}")

    def test_inferred_foreign_key_join_matches(self) -> None:
        self._assert_same_sql("SELECT id, user.name, user.email FROM postgres.orders")

    def test_explicit_foreign_key_join_matches(self) -> None:
        self._assert_same_sql("SELECT id, order.amount FROM postgres.line_items")

    def test_data_warehouse_join_matches(self) -> None:
        self._assert_same_sql("SELECT id, user_join.email FROM postgres.orders")

    def test_persons_source_join_matches(self) -> None:
        self._assert_same_sql("SELECT orders_join.amount FROM persons")

    def test_bare_table_name_matches(self) -> None:
        self._assert_same_sql("SELECT id, amount FROM orders")
