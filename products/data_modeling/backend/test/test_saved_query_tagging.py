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
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


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

    @contextmanager
    def captured_tags(self) -> Iterator[list[list[str] | None]]:
        captured: list[list[str] | None] = []

        def execute(*args: Any, **kwargs: Any) -> Any:
            captured.append(get_query_tags().saved_query_ids)
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
            ("plain_view", "SELECT id FROM demand_view", "view"),
            ("materialized_view_backing_table", "SELECT id FROM demand_matview", "matview"),
            ("no_saved_query", "SELECT 1", None),
        ]
    )
    def test_execution_tags_the_saved_queries_the_resolver_bound(self, _name: str, query: str, expected: str | None):
        with tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY), self.captured_tags() as captured:
            with suppress(_Captured):
                self.executor(query).execute()
        self.assertEqual(captured, [[str(getattr(self, expected).pk)] if expected else None])

    def test_context_reuse_and_cte_shadowing_do_not_tag(self) -> None:
        context = HogQLContext(team=self.team, database=Database.create_for(team=self.team))
        self.executor("SELECT id FROM demand_view", context).generate_clickhouse_sql()
        with tags_context(product=Product.WAREHOUSE, feature=Feature.QUERY), self.captured_tags() as captured:
            with suppress(_Captured):
                self.executor("WITH demand_view AS (SELECT 2 AS id) SELECT id FROM demand_view", context).execute()
        self.assertEqual(captured, [None])

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
        for saved_query_ids in captured:
            self.assertIn(str(self.view.pk), saved_query_ids or [])
