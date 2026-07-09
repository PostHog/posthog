from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseNode,
    EventsNode,
    FunnelsDataWarehouseNode,
    HogQLQuery,
    InsightActorsQuery,
    LifecycleDataWarehouseNode,
    TrendsQuery,
)

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.hogql_queries.access_controlled_resources import (
    _references_data_warehouse,
    queried_access_controlled_resources,
    warehouse_names_cache_scope,
)

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestQueriedAccessControlledResources(BaseTest):
    def _create_warehouse_table(self, name: str) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            url_pattern="https://bucket.s3/data/*",
            columns={},
        )

    @staticmethod
    def _dw_node() -> DataWarehouseNode:
        return DataWarehouseNode(
            id="some_dw_table",
            id_field="id",
            distinct_id_field="distinct_id",
            table_name="some_dw_table",
            timestamp_field="timestamp",
        )

    @parameterized.expand(
        [
            ("system_table", "select * from system.notebooks", {"notebook"}),
            ("through_subquery", "select * from (select * from system.notebooks)", {"notebook"}),
            ("through_cte_body", "with n as (select 1 from system.notebooks) select * from n", {"notebook"}),
            ("multiple", "select 1 from system.notebooks, system.surveys", {"notebook", "survey"}),
            ("no_access_controlled_table", "select 1", set()),
            ("events_table", "select * from events", set()),
        ]
    )
    def test_hogql_query_system_scopes(self, _name, sql, expected):
        assert queried_access_controlled_resources(HogQLQuery(query=sql), self.team) == expected

    def test_unparseable_hogql_fails_closed(self):
        assert queried_access_controlled_resources(HogQLQuery(query="select from from"), self.team) is None

    def test_structured_query_reads_no_system_table(self):
        query = TrendsQuery(series=[EventsNode(event="$pageview")])
        assert queried_access_controlled_resources(query, self.team) == set()

    def test_structured_query_with_data_warehouse_series(self):
        query = TrendsQuery(series=[EventsNode(event="$pageview"), self._dw_node()])
        assert queried_access_controlled_resources(query, self.team) == {"warehouse_table", "warehouse_view"}

    def test_nested_data_warehouse_node_is_detected(self):
        # The node is two levels deep (actors query -> source insight -> series), so a shallow
        # series-only check would miss it; the recursive walk must catch it (else the cache leaks).
        query = InsightActorsQuery(source=TrendsQuery(series=[self._dw_node()]))
        assert queried_access_controlled_resources(query, self.team) == {"warehouse_table", "warehouse_view"}

    def test_references_data_warehouse_covers_all_variants_and_nesting(self):
        variants = [
            DataWarehouseNode(id="t", id_field="id", distinct_id_field="d", table_name="t", timestamp_field="ts"),
            FunnelsDataWarehouseNode(
                id="t", id_field="id", aggregation_target_field="x", table_name="t", timestamp_field="ts"
            ),
            LifecycleDataWarehouseNode(
                id="t", aggregation_target_field="x", created_at_field="c", table_name="t", timestamp_field="ts"
            ),
        ]
        for node in variants:
            assert _references_data_warehouse(node) is True
            assert _references_data_warehouse([node]) is True  # nested in a list
            assert _references_data_warehouse({"a": {"b": [node]}}) is True  # nested in dicts/lists
        assert _references_data_warehouse(EventsNode(event="$pageview")) is False
        assert _references_data_warehouse(TrendsQuery(series=[EventsNode(event="$pageview")])) is False

    def test_warehouse_table_scope(self):
        self._create_warehouse_table("my_warehouse_table")
        result = queried_access_controlled_resources(HogQLQuery(query="select * from my_warehouse_table"), self.team)
        assert result == {"warehouse_table"}

    def test_external_warehouse_table_matched_by_raw_name(self):
        # External tables are queryable under BOTH their raw name and the prefixed
        # source_type.prefix.table key. A user denied the table could otherwise query the raw
        # name and be served an allowed user's cached rows, since only the prefixed form was matched.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="s",
            connection_id="c",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="myprefix",
        )
        table = self._create_warehouse_table("stripe_customers")
        table.external_data_source = source
        table.save()

        # The two queryable names genuinely diverge, so matching only the prefixed form left a gap.
        assert get_data_warehouse_table_name(source, table.name) != table.name

        result = queried_access_controlled_resources(HogQLQuery(query="select * from stripe_customers"), self.team)
        assert result == {"warehouse_table"}

    def test_warehouse_view_scope(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_warehouse_view", query={"kind": "HogQLQuery", "query": "select 1 as a"}
        )
        result = queried_access_controlled_resources(HogQLQuery(query="select * from my_warehouse_view"), self.team)
        # warehouse_table is included too: a non-materialized view reads underlying tables, and a cache
        # hit skips that resolution, so the user's table denials must partition the key.
        assert result == {"warehouse_view", "warehouse_table"}

    def test_warehouse_and_system_scopes_combined(self):
        self._create_warehouse_table("my_warehouse_table")
        result = queried_access_controlled_resources(
            HogQLQuery(query="select 1 from my_warehouse_table, system.notebooks"), self.team
        )
        assert result == {"warehouse_table", "notebook"}

    def test_catalog_lookup_is_memoized_within_scope_and_fetches_narrowly(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="s",
            connection_id="c",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="myprefix",
        )
        table = self._create_warehouse_table("stripe_customers")
        table.external_data_source = source
        table.save()

        query = HogQLQuery(query="select * from stripe_customers")
        with warehouse_names_cache_scope():
            # One query each for tables and views. A third means the .only() field list no
            # longer covers what get_data_warehouse_table_name reads, i.e. a per-row defer-load.
            with self.assertNumQueries(2):
                assert queried_access_controlled_resources(query, self.team) == {"warehouse_table"}
            with self.assertNumQueries(0):
                assert queried_access_controlled_resources(query, self.team) == {"warehouse_table"}

    def test_catalog_writes_invalidate_the_scope_cache(self):
        query = HogQLQuery(query="select * from fresh_table")
        with warehouse_names_cache_scope():
            assert queried_access_controlled_resources(query, self.team) == set()
            # post_save must clear the scope cache, or this table would be fingerprinted as
            # nonexistent (unpartitioned cache key) for the rest of the request.
            self._create_warehouse_table("fresh_table")
            assert queried_access_controlled_resources(query, self.team) == {"warehouse_table"}

    def test_catalog_lookup_is_uncached_outside_a_scope(self):
        self._create_warehouse_table("my_warehouse_table")
        query = HogQLQuery(query="select * from my_warehouse_table")
        queried_access_controlled_resources(query, self.team)
        # No scope is active, so nothing may be cached: a cache outliving the request/task
        # scope could fingerprint against a stale catalog after access-relevant rows change.
        with self.assertNumQueries(2):
            assert queried_access_controlled_resources(query, self.team) == {"warehouse_table"}

    def test_warehouse_table_of_another_team_not_matched(self):
        from posthog.models import Team

        other_team = Team.objects.create(organization=self.organization)
        DataWarehouseTable.objects.create(
            name="other_team_table",
            format="Parquet",
            team=other_team,
            url_pattern="https://bucket.s3/data/*",
            columns={},
        )
        # A name that resolves to a warehouse table in a different team must not grant the scope here.
        result = queried_access_controlled_resources(HogQLQuery(query="select * from other_team_table"), self.team)
        assert result == set()
