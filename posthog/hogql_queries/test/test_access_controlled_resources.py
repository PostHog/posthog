from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

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

from posthog.caching.warehouse_name_cache import warehouse_names_cache_scope
from posthog.hogql_queries.access_controlled_resources import (
    _references_data_warehouse,
    queried_access_controlled_resources,
)

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


def _create_warehouse_table(team, name: str) -> DataWarehouseTable:
    return DataWarehouseTable.objects.create(
        name=name,
        format="Parquet",
        team=team,
        url_pattern="https://bucket.s3/data/*",
        columns={},
    )


class TestQueriedAccessControlledResources(BaseTest):
    def _create_warehouse_table(self, name: str) -> DataWarehouseTable:
        return _create_warehouse_table(self.team, name)

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


class TestWarehouseNamesMemoization(BaseTest):
    def _scan_counts(self, ctx: CaptureQueriesContext) -> tuple[int, int]:
        table_scans = [q["sql"] for q in ctx.captured_queries if "posthog_datawarehousetable" in q["sql"]]
        view_scans = [q["sql"] for q in ctx.captured_queries if "posthog_datawarehousesavedquery" in q["sql"]]
        return len(table_scans), len(view_scans)

    def test_warehouse_lookups_memoized_within_scope(self):
        # A dashboard load fingerprints one query per tile; without the scope cache each fingerprint
        # rescans every warehouse table and saved query of the team.
        _create_warehouse_table(self.team, "my_warehouse_table")

        with warehouse_names_cache_scope(), CaptureQueriesContext(connection) as ctx:
            first = queried_access_controlled_resources(HogQLQuery(query="select * from my_warehouse_table"), self.team)
            second = queried_access_controlled_resources(
                HogQLQuery(query="select * from my_warehouse_table"), self.team
            )

        assert first == second == {"warehouse_table"}
        assert self._scan_counts(ctx) == (1, 1)

    def test_no_memoization_outside_scope(self):
        # No scope must mean no caching: a thread-lifetime cache on a worker would fingerprint
        # queries against a stale view of the team's warehouse objects.
        with CaptureQueriesContext(connection) as ctx:
            queried_access_controlled_resources(HogQLQuery(query="select * from some_table"), self.team)
            queried_access_controlled_resources(HogQLQuery(query="select * from some_table"), self.team)

        assert self._scan_counts(ctx) == (2, 2)

    @parameterized.expand(
        [
            (
                "table",
                lambda self: _create_warehouse_table(self.team, "fresh_object"),
                {"warehouse_table"},
            ),
            (
                "view",
                lambda self: DataWarehouseSavedQuery.objects.create(
                    team=self.team, name="fresh_object", query={"kind": "HogQLQuery", "query": "select 1 as a"}
                ),
                {"warehouse_view", "warehouse_table"},
            ),
        ]
    )
    def test_create_and_soft_delete_invalidate_within_scope(self, _name, create, expected_scopes):
        # Within one scope, warehouse object changes must invalidate the memo — a fingerprint
        # computed against pre-change names would partition the query cache wrong for the rest of
        # the request/task.
        query = HogQLQuery(query="select * from fresh_object")
        with warehouse_names_cache_scope():
            assert queried_access_controlled_resources(query, self.team) == set()
            obj = create(self)
            assert queried_access_controlled_resources(query, self.team) == expected_scopes
            obj.soft_delete()
            assert queried_access_controlled_resources(query, self.team) == set()

    def test_source_change_invalidates_within_scope(self):
        # The prefixed queryable name depends on the source's prefix, so source edits must
        # invalidate too, not just table/view rows.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="s",
            connection_id="c",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="before",
        )
        table = _create_warehouse_table(self.team, "stripe_customers")
        table.external_data_source = source
        table.save()

        query = HogQLQuery(query="select * from stripe.after.customers")
        with warehouse_names_cache_scope():
            assert queried_access_controlled_resources(query, self.team) == set()
            source.prefix = "after"
            source.save()
            assert queried_access_controlled_resources(query, self.team) == {"warehouse_table"}
