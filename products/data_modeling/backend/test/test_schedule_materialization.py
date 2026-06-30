from datetime import timedelta

from posthog.test.base import BaseTest
from unittest import mock

from django.db import OperationalError

from products.data_modeling.backend.models import DAG, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType

SERVICE = "products.data_warehouse.backend.logic.data_load.saved_query_service"
GET_V2_DAG_IDS = "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids"


class TestScheduleMaterializationV2Guard(BaseTest):
    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name="Default")
        self.sq = DataWarehouseSavedQuery.objects.create(
            name="view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=timedelta(hours=12),
        )
        Node.objects.create(team=self.team, dag=self.dag, saved_query=self.sq, type=NodeType.VIEW)

    def test_skips_v1_and_nulls_frequency_when_dag_on_v2(self):
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch(f"{SERVICE}.sync_saved_query_workflow") as sync_wf,
            mock.patch(f"{SERVICE}.saved_query_workflow_exists", return_value=False),
            mock.patch.object(DataWarehouseSavedQuery, "setup_model_paths") as setup_paths,
        ):
            self.sq.schedule_materialization()
        sync_wf.assert_not_called()
        setup_paths.assert_not_called()
        self.sq.refresh_from_db()
        assert self.sq.sync_frequency_interval is None

    def test_creates_v1_schedule_when_dag_not_on_v2(self):
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{SERVICE}.sync_saved_query_workflow") as sync_wf,
            mock.patch(f"{SERVICE}.saved_query_workflow_exists", return_value=False),
            mock.patch.object(DataWarehouseSavedQuery, "setup_model_paths"),
        ):
            self.sq.schedule_materialization()
        sync_wf.assert_called_once()
        self.sq.refresh_from_db()
        assert self.sq.sync_frequency_interval == timedelta(hours=12)

    def test_disables_materialization_when_v2_lookup_fails(self):
        self.sq.is_materialized = True
        self.sq.save(update_fields=["is_materialized"])
        with (
            mock.patch(GET_V2_DAG_IDS, side_effect=Exception("temporal unavailable")),
            mock.patch(f"{SERVICE}.sync_saved_query_workflow") as sync_wf,
            mock.patch(f"{SERVICE}.saved_query_workflow_exists", return_value=False),
            mock.patch.object(DataWarehouseSavedQuery, "setup_model_paths"),
        ):
            self.sq.schedule_materialization()
        sync_wf.assert_not_called()
        self.sq.refresh_from_db()
        assert self.sq.is_materialized is False

    def test_recovery_save_on_closed_connection_does_not_propagate(self):
        # Mirrors the production failure: pool starvation makes scheduling fail with a connection
        # the server already closed, so the recovery save() itself raises "the connection is
        # closed". That must not turn a recoverable timeout into a hard crash out of
        # schedule_materialization.
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{SERVICE}.saved_query_workflow_exists", return_value=False),
            mock.patch.object(DataWarehouseSavedQuery, "setup_model_paths"),
            mock.patch(
                f"{SERVICE}.sync_saved_query_workflow",
                side_effect=OperationalError("query_wait_timeout"),
            ),
            mock.patch.object(
                DataWarehouseSavedQuery,
                "save",
                side_effect=OperationalError("the connection is closed"),
            ),
        ):
            # Must not raise even though both the scheduling and the recovery save fail.
            self.sq.schedule_materialization()
