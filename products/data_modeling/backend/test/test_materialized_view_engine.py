from contextlib import nullcontext
from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.modifiers import create_default_modifiers_for_team, materialized_view_engine_scope

from posthog.schema_enums import MaterializedViewEngine

from products.data_modeling.backend.facade.contracts import MaterializationEngine
from products.data_modeling.backend.facade.models import NodeEngineTable
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

HOGQL_QUERY: dict[str, Any] = {"query": "SELECT 1 AS id", "kind": "HogQLQuery"}
RAW_TRINO_QUERY: dict[str, Any] = {
    "query": "SELECT 1 AS id",
    "kind": "HogQLQuery",
    "executionTarget": "managed_trino",
    "sendRawQuery": True,
}


class TestMaterializedViewEngine(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dag = DAG.get_or_create_default(self.team)
        self.credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )

    def _table(self, name: str) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            format="Parquet",
            columns={"id": "String"},
            credential=self.credential,
            url_pattern=f"s3://bucket/{name}/*.parquet",
        )

    def _view(
        self,
        name: str,
        *,
        query: dict[str, Any] = HOGQL_QUERY,
        clickhouse_table: bool = False,
        trino_table: bool = False,
        is_materialized: bool = True,
    ) -> DataWarehouseSavedQuery:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query=query,
            columns={"id": "String"},
            is_materialized=is_materialized,
            table=self._table(f"{name}_clickhouse") if clickhouse_table else None,
        )
        node = Node.objects.create(team=self.team, dag=self.dag, saved_query=saved_query, type=NodeType.MAT_VIEW)
        if trino_table:
            NodeEngineTable.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                node=node,
                engine=MaterializationEngine.TRINO,
                table=self._table(f"{name}_trino"),
            )
        return saved_query

    def _database(self, *, engine: MaterializedViewEngine | None) -> Database:
        with materialized_view_engine_scope(engine) if engine else nullcontext():
            modifiers = create_default_modifiers_for_team(self.team, HogQLQueryModifiers(useMaterializedViews=True))
            return Database.create_for(team=self.team, modifiers=modifiers)

    def _read(self, name: str, *, engine: MaterializedViewEngine | None) -> S3Table | None:
        database = self._database(engine=engine)
        if not database.has_table(name):
            return None
        table = database.get_table(name)
        assert isinstance(table, S3Table)
        return table

    def _source_table_id(self, view_name: str, engine: str) -> str:
        return str(DataWarehouseTable.objects.get(team=self.team, name=f"{view_name}_{engine}").id)

    @parameterized.expand(
        [
            ("hogql_view", HOGQL_QUERY, True),
            ("raw_trino_view", RAW_TRINO_QUERY, False),
        ]
    )
    def test_a_trino_read_serves_the_trino_copy(self, _name: str, query: dict[str, Any], has_clickhouse_copy: bool):
        self._view("orders", query=query, clickhouse_table=has_clickhouse_copy, trino_table=True)

        trino_read = self._read("orders", engine=MaterializedViewEngine.TRINO)
        default_read = self._read("orders", engine=None)

        assert trino_read is not None
        assert trino_read.table_id == self._source_table_id("orders", "trino")
        if has_clickhouse_copy:
            assert default_read is not None
            assert default_read.table_id == self._source_table_id("orders", "clickhouse")
        else:
            assert default_read is None

    def test_a_trino_read_falls_back_to_the_clickhouse_table_without_a_trino_copy(self):
        self._view("orders", clickhouse_table=True)

        read = self._read("orders", engine=MaterializedViewEngine.TRINO)

        assert read is not None
        assert read.table_id == self._source_table_id("orders", "clickhouse")

    def test_a_raw_trino_view_without_a_trino_copy_stays_unreadable(self):
        self._view("orders", query=RAW_TRINO_QUERY)

        assert self._read("orders", engine=MaterializedViewEngine.TRINO) is None

    def test_a_view_that_stopped_materializing_ignores_its_stale_trino_copy(self):
        self._view("orders", clickhouse_table=True, trino_table=True, is_materialized=False)

        table = self._database(engine=MaterializedViewEngine.TRINO).get_table("orders")

        assert isinstance(table, SavedQuery)

    @parameterized.expand(
        [
            ("trino_read", MaterializedViewEngine.TRINO),
            ("clickhouse_read", MaterializedViewEngine.CLICKHOUSE),
            ("default_read", None),
        ]
    )
    def test_the_trino_copy_is_not_listed_as_a_warehouse_table(self, _name: str, engine: MaterializedViewEngine | None):
        self._view("orders", clickhouse_table=True, trino_table=True)

        database = self._database(engine=engine)

        assert not database.has_table("orders_trino")

    @parameterized.expand(
        [
            ("requested_by_the_query", {"materializedViewEngine": "trino"}, {}),
            ("stored_on_the_project", {}, {"materializedViewEngine": "trino"}),
        ]
    )
    def test_a_client_cannot_choose_the_engine(
        self, _name: str, requested: dict[str, Any], stored: dict[str, Any]
    ) -> None:
        self.team.modifiers = stored
        self.team.save()
        self._view("orders", clickhouse_table=True, trino_table=True)

        modifiers = create_default_modifiers_for_team(self.team, HogQLQueryModifiers(**requested))
        database = Database.create_for(team=self.team, modifiers=modifiers)

        assert modifiers.materializedViewEngine is None
        table = database.get_table("orders")
        assert isinstance(table, S3Table)
        assert table.table_id == self._source_table_id("orders", "clickhouse")
