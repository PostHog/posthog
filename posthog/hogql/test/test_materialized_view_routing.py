from datetime import timedelta

from posthog.test.base import BaseTest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.clickhouse.workload import Workload

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestMaterializedViewRouting(BaseTest):
    def setUp(self):
        super().setUp()
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        backing_table = DataWarehouseTable.objects.create(
            name="mv_backing",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/mv_backing/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"kind": "HogQLQuery", "query": "SELECT id FROM some_source"},
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String"}},
            table=backing_table,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=1),
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

    def _workload_for(self, query: str, *, routing_enabled: bool) -> Workload | None:
        modifiers = create_default_modifiers_for_team(
            self.team,
            HogQLQueryModifiers(useEndpointsClusterForMaterializedViewOnlyQueries=routing_enabled),
        )
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True, modifiers=modifiers)
        prepare_ast_for_printing(parse_select(query), context=context, dialect="clickhouse")
        return context.workload

    def test_matview_only_query_routes_to_endpoints_cluster(self):
        assert self._workload_for("SELECT id FROM my_view", routing_enabled=True) == Workload.ENDPOINTS

    def test_matview_only_query_stays_default_when_routing_disabled(self):
        assert self._workload_for("SELECT id FROM my_view", routing_enabled=False) != Workload.ENDPOINTS

    def test_matview_query_touching_events_stays_default(self):
        # Referencing events (resolved through the real pipeline) disqualifies routing.
        workload = self._workload_for("SELECT id, (SELECT count() FROM events) AS c FROM my_view", routing_enabled=True)
        assert workload != Workload.ENDPOINTS
