from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.models import DataModelingJob
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

HOUR = timedelta(hours=1)


class TestViewFreshnessWarnings(BaseTest):
    def _materialized_view(self, *, is_materialized: bool = True) -> DataWarehouseSavedQuery:
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        table = DataWarehouseTable.objects.create(
            name="mrr_daily_backing",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            team=self.team,
            credential=credential,
            url_pattern="s3://test/mrr_daily/*",
            columns={"mrr": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}},
        )
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="mrr_daily",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS mrr"},
            columns={"mrr": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}},
            table=table,
            is_materialized=is_materialized,
        )

    def _target(self, view: DataWarehouseSavedQuery, target: timedelta) -> None:
        dag = DAG.objects.create(team=self.team, name="dag")
        node = Node.objects.create(team=self.team, dag=dag, saved_query=view, type=NodeType.MAT_VIEW)
        set_declared_target(node, target)

    def _job(self, view: DataWarehouseSavedQuery, status: str, hours_ago: float) -> None:
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=view,
            status=status,
            engine="clickhouse",
            last_run_at=timezone.now() - timedelta(hours=hours_ago),
        )

    @parameterized.expand(
        [
            ("late_view_warns", HOUR, [("Completed", 3)], None, "Stale"),
            ("fresh_view_is_silent", HOUR, [("Completed", 1.5)], None, None),
            ("job_success_beats_frozen_legacy_stamp", HOUR, [("Completed", 0.5)], 72, None),
            ("failed_latest_attempt_says_so", HOUR, [("Completed", 5), ("Failed", 0.5)], None, "Failed"),
            ("no_cadence_is_silent", None, [("Completed", 72)], None, None),
            ("never_materialized_is_silent", HOUR, [("Failed", 0.5)], None, None),
        ]
    )
    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_query_over_a_materialized_view_warns_when_it_is_late(
        self,
        _name: str,
        target: timedelta | None,
        jobs: list[tuple[str, float]],
        legacy_hours_ago: float | None,
        expected_status: str | None,
        _sync_execute: Any,
    ) -> None:
        view = self._materialized_view()
        if legacy_hours_ago is not None:
            view.last_run_at = timezone.now() - timedelta(hours=legacy_hours_ago)
            view.save(update_fields=["last_run_at"])
        if target is not None:
            self._target(view, target)
        for status, hours_ago in jobs:
            self._job(view, status, hours_ago)

        response = execute_hogql_query("SELECT mrr FROM mrr_daily", team=self.team)

        warnings = [w for w in response.warnings or [] if w.type == "warehouse_sync"]
        if expected_status is None:
            assert warnings == []
        else:
            assert [(w.table_name, w.status, w.data_is_current) for w in warnings] == [
                ("mrr_daily", expected_status, False)
            ]
            assert "`mrr_daily`" in warnings[0].message

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_unmaterialized_view_reads_its_sources_and_never_warns(self, _sync_execute: Any) -> None:
        view = self._materialized_view(is_materialized=False)
        self._target(view, HOUR)
        self._job(view, "Completed", 72)

        response = execute_hogql_query("SELECT mrr FROM mrr_daily", team=self.team)

        assert not response.warnings
