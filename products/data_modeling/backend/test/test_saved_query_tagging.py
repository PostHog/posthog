from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tags_context

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

ReadTags = tuple[list[str] | None, list[str] | None, list[str] | None]
NO_READS: ReadTags = (None, None, None)
ID_COLUMNS = {
    "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
    "distinct_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
}


class _Captured(Exception):
    pass


class TestSavedQueryTagging(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="demand_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id, now() AS created_at, 'd' AS distinct_id"},
            columns={"id": "Int64", "created_at": "DateTime", "distinct_id": "String"},
        )
        credentials = DataWarehouseCredential.objects.create(team=self.team, access_key="fake", access_secret="fake")
        self.orders_raw = self.warehouse_table("orders_raw", credentials)
        self.customers_raw = self.warehouse_table("customers_raw", credentials)
        self.order_lines = self.saved_query("order_lines", "SELECT id, distinct_id FROM orders_raw")
        self.order_summary = self.saved_query("order_summary", "SELECT id FROM order_lines")
        self.all_ids = self.saved_query("all_ids", "SELECT id FROM orders_raw UNION ALL SELECT id FROM customers_raw")
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="customers_raw",
            joining_table_key="distinct_id",
            field_name="customer",
        )
        self.customer_events = self.saved_query("customer_events", "SELECT events.customer.id AS id FROM events")
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="demand_matview",
            format="Parquet",
            credential=credentials,
            url_pattern="https://example.com/data/*.parquet",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True}},
        )
        self.matview = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="demand_matview",
            query={"kind": "HogQLQuery", "query": "SELECT id FROM demand_view"},
            columns={"id": "Int64"},
            table=table,
            is_materialized=True,
        )

    def warehouse_table(self, name: str, credentials: DataWarehouseCredential) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            format="Parquet",
            credential=credentials,
            url_pattern=f"https://example.com/{name}/*.parquet",
            columns=ID_COLUMNS,
        )

    def saved_query(self, name: str, query: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": query},
            columns={"id": "Int64", "distinct_id": "String"},
        )

    def ids(self, *names: str) -> list[str] | None:
        return sorted(str(getattr(self, name).pk) for name in names) or None

    @contextmanager
    def captured_tags(self) -> Iterator[list[ReadTags]]:
        captured: list[ReadTags] = []

        def execute(*args: Any, **kwargs: Any) -> Any:
            tags = get_query_tags()
            captured.append((tags.saved_query_ids, tags.warehouse_table_ids, tags.directly_read_ids))
            raise _Captured()

        with patch("posthog.hogql.query.sync_execute", side_effect=execute):
            yield captured

    def executor(self, query: str, context: HogQLContext | None = None) -> HogQLQueryExecutor:
        return HogQLQueryExecutor(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useMaterializedViews=True),
            context=context or HogQLContext(team=self.team),
        )

    @parameterized.expand(
        [
            ("plain_view", "SELECT id FROM demand_view", ["view"], [], ["view"]),
            ("materialized_view_backing_table", "SELECT id FROM demand_matview", ["matview"], [], ["matview"]),
            ("warehouse_table", "SELECT id FROM orders_raw", [], ["orders_raw"], ["orders_raw"]),
            (
                "nested_views",
                "SELECT id FROM order_summary",
                ["order_summary", "order_lines"],
                ["orders_raw"],
                ["order_summary"],
            ),
            (
                "view_joined_to_table",
                "SELECT s.id FROM order_summary s JOIN customers_raw c ON s.id = c.id",
                ["order_summary", "order_lines"],
                ["orders_raw", "customers_raw"],
                ["order_summary", "customers_raw"],
            ),
            (
                "lazy_join_in_view_body",
                "SELECT id FROM customer_events",
                ["customer_events"],
                ["customers_raw"],
                ["customer_events"],
            ),
            ("top_level_lazy_join", "SELECT events.customer.id FROM events", [], ["customers_raw"], ["customers_raw"]),
            ("union_view", "SELECT id FROM all_ids", ["all_ids"], ["orders_raw", "customers_raw"], ["all_ids"]),
            ("no_saved_query", "SELECT 1", [], [], []),
        ]
    )
    def test_execution_tags_the_views_and_tables_the_resolver_bound(
        self, _name: str, query: str, views: list[str], tables: list[str], direct: list[str]
    ) -> None:
        with tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY), self.captured_tags() as captured:
            with suppress(_Captured):
                self.executor(query).execute()
        self.assertEqual(captured, [(self.ids(*views), self.ids(*tables), self.ids(*direct))])

    def test_context_reuse_and_cte_shadowing_do_not_tag(self) -> None:
        context = HogQLContext(team=self.team, database=Database.create_for(team=self.team))
        self.executor("SELECT id FROM demand_view", context).generate_clickhouse_sql()
        with tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY), self.captured_tags() as captured:
            with suppress(_Captured):
                self.executor("WITH demand_view AS (SELECT 2 AS id) SELECT id FROM demand_view", context).execute()
        self.assertEqual(captured, [NO_READS])

    def run_query_api(self) -> None:
        self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {"query": HogQLQuery(query="SELECT id FROM demand_view").model_dump()},
        )

    def run_endpoint(self) -> None:
        self.client.post(
            f"/api/environments/{self.team.id}/endpoints/",
            {"name": "demand_view_feed", "query": {"kind": "HogQLQuery", "query": "SELECT id FROM demand_view"}},
            format="json",
        )
        self.client.post(f"/api/environments/{self.team.id}/endpoints/demand_view_feed/run/", {}, format="json")

    @parameterized.expand([("query_api",), ("endpoint",)])
    def test_every_entry_point_carries_the_tag(self, entry_point: str) -> None:
        with self.captured_tags() as captured:
            with suppress(Exception):
                getattr(self, f"run_{entry_point}")()
        self.assertTrue(captured, f"{entry_point} never reached ClickHouse")
        for saved_query_ids, _tables, _direct in captured:
            self.assertIn(str(self.view.pk), saved_query_ids or [])
