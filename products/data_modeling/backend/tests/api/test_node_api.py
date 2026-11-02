from datetime import timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models import Team

from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.logic.node_materialization import start_node_materialization
from products.data_modeling.backend.logic.node_suspension import (
    mark_node_suspended,
    suspension_reset_at,
    suspension_state,
)
from products.data_modeling.backend.models import (
    DAG,
    DataModelingJob,
    DataModelingJobEngine,
    DataWarehouseManagedViewSet,
    Edge,
    Node,
    NodeType,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind


def _managed_viewset(team: Team) -> DataWarehouseManagedViewSet:
    return DataWarehouseManagedViewSet.objects.create(team=team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)


class TestNodeViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag_id = f"posthog_{self.team.id}"
        self.dag = DAG.objects.create(team=self.team, name=self.dag_id)

        self.saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        self.table_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="events",
            type=NodeType.TABLE,
        )

        self.view_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            saved_query=self.saved_query,
            type=NodeType.VIEW,
        )

        Edge.objects.create(
            team=self.team,
            dag=self.dag,
            source=self.table_node,
            target=self.view_node,
        )

    def test_list_nodes(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

        names = {node["name"] for node in response.json()["results"]}
        self.assertEqual(names, {"events", "test_view"})

    @parameterized.expand(["saved_query", "warehouse_table", "posthog_table", "metric"])
    def test_retrieve_node_by_backing_resource(self, lookup):
        if lookup == "saved_query":
            resource_id = self.saved_query.id
            expected_node = self.view_node
        elif lookup == "metric":
            resource_id = uuid4()
            expected_node = Node.objects.create(
                team=self.team, dag=self.dag, name="revenue", type=NodeType.METRIC, metric_id=resource_id
            )
        elif lookup == "warehouse_table":
            resource_id = uuid4()
            self.table_node.properties = {"origin": "warehouse", "warehouse_table_id": str(resource_id)}
            self.table_node.save(update_fields=["properties"])
            expected_node = self.table_node
        else:
            resource_id = self.table_node.name
            self.table_node.properties = {"origin": "posthog"}
            self.table_node.save(update_fields=["properties"])
            expected_node = self.table_node

        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{resource_id}/?lookup={lookup}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(expected_node.id))

    def test_soft_deleting_a_saved_query_deletes_its_node_and_unread_parents(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.saved_query.soft_delete()

        self.assertFalse(Node.objects.filter(id__in=[self.view_node.id, self.table_node.id]).exists())

    def _node_payload(self) -> dict:
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    @parameterized.expand(
        [
            ("legacy_duckgres", DataModelingJobEngine.LEGACY_DUCKGRES),
            ("managed_warehouse", DataModelingJobEngine.MANAGED_WAREHOUSE),
        ]
    )
    def test_a_shadow_failure_does_not_mark_a_served_model_failed(self, _name: str, shadow_engine: str):
        """The shadow run finishes after the serving one, so reading the newest job of any engine
        would report a model that served fine as failed."""
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.COMPLETED,
            engine=DataModelingJobEngine.CLICKHOUSE,
            last_run_at=timezone.now() - timedelta(minutes=10),
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.FAILED,
            engine=shadow_engine,
            last_run_at=timezone.now(),
        )

        self.assertEqual(self._node_payload()["last_run_status"], "Completed")

    def test_the_reported_error_belongs_to_the_run_that_reported_the_status(self):
        """The saved query's latest_error is a v1 field the DAG path never writes, so the error
        has to come off the job or the attention table shows a failure with no reason."""
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.FAILED,
            error="Code: 241. Memory limit exceeded",
            last_run_at=timezone.now(),
        )

        payload = self._node_payload()

        self.assertEqual(payload["last_run_status"], "Failed")
        self.assertEqual(payload["last_run_error"], "Code: 241. Memory limit exceeded")

    def test_a_model_that_last_succeeded_reports_no_error(self):
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.FAILED,
            error="an old failure",
            last_run_at=timezone.now() - timedelta(hours=2),
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.COMPLETED,
            last_run_at=timezone.now(),
        )

        self.assertIsNone(self._node_payload()["last_run_error"])

    def test_a_skipped_run_is_reported_over_the_stored_status(self):
        """Skipped jobs are written straight to the job table, so the stored status still holds the
        success before them."""
        self.view_node.properties = {"system": {"last_run_status": "Completed"}}
        self.view_node.save(update_fields=["properties"])
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.SKIPPED,
            last_run_at=timezone.now(),
        )

        self.assertEqual(self._node_payload()["last_run_status"], "Skipped")

    def test_last_run_at_reports_the_newest_success_not_a_failed_run(self):
        """The stored stamp is written on failures too, so trusting it would report a broken model
        as freshly refreshed."""
        succeeded_at = timezone.now() - timedelta(hours=3)
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.COMPLETED,
            last_run_at=succeeded_at,
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.FAILED,
            last_run_at=timezone.now(),
        )
        self.view_node.properties = {"system": {"last_run_at": timezone.now().isoformat()}}
        self.view_node.save(update_fields=["properties"])

        payload = self._node_payload()
        self.assertEqual(payload["last_run_status"], "Failed")
        self.assertEqual(payload["last_run_at"][:16], succeeded_at.isoformat()[:16])

    @parameterized.expand([("failed_history", True), ("no_history", False)])
    def test_legacy_last_run_at_is_used_only_without_job_history(self, _name: str, has_failed_job: bool):
        legacy_run_at = timezone.now() - timedelta(days=1)
        self.view_node.properties = {"system": {"last_run_at": legacy_run_at.isoformat()}}
        self.view_node.save(update_fields=["properties"])
        if has_failed_job:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=self.saved_query,
                status=DataModelingJob.Status.FAILED,
                last_run_at=timezone.now(),
            )

        self.assertEqual(self._node_payload()["last_run_at"], None if has_failed_job else legacy_run_at.isoformat())

    @parameterized.expand([("list",), ("retrieve",)])
    def test_nodes_report_status_from_the_latest_job(self, endpoint: str):
        """The node carries no status of its own, so both reads have to take it off the newest job."""
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.COMPLETED,
            last_run_at=timezone.now() - timedelta(hours=2),
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.FAILED,
            last_run_at=timezone.now(),
        )

        base = f"/api/environments/{self.team.id}/data_modeling_nodes/"
        if endpoint == "list":
            response = self.client.get(base)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            statuses = {node["name"]: node["last_run_status"] for node in response.json()["results"]}
        else:
            statuses = {}
            for node in (self.view_node, self.table_node):
                response = self.client.get(f"{base}{node.id}/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                statuses[response.json()["name"]] = response.json()["last_run_status"]

        self.assertEqual(statuses["test_view"], "Failed")
        self.assertIsNone(statuses["events"])

    def test_list_nodes_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_table",
            type=NodeType.TABLE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

    def test_get_node(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "test_view")
        self.assertEqual(response.json()["type"], "view")

    @parameterized.expand(
        [
            (
                "warehouse",
                {"origin": "warehouse", "warehouse_table_id": "dbd0dfd6-ae37-4733-a065-0f2601ac3a67"},
                "warehouse",
                "dbd0dfd6-ae37-4733-a065-0f2601ac3a67",
            ),
            ("posthog", {"origin": "posthog"}, "posthog", None),
            ("empty", {}, None, None),
            ("malformed", {"origin": "other", "warehouse_table_id": "not-a-uuid"}, None, None),
        ]
    )
    def test_get_node_exposes_valid_table_identity(self, _name, properties, origin, warehouse_table_id):
        self.table_node.properties = properties
        self.table_node.save(update_fields=["properties"])

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.table_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["origin"], origin)
        self.assertEqual(response.json()["warehouse_table_id"], warehouse_table_id)

    def test_get_node_includes_upstream_downstream_counts(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["upstream_count"], 0)
        self.assertEqual(response.json()["downstream_count"], 0)

    @parameterized.expand(
        [
            # node target wins even when the saved-query interval disagrees (tiered v2 teams
            # carry NULL intervals, so a saved-query-only read shows a blank frequency)
            ("target_first", timedelta(hours=6), timedelta(hours=12), "6hour"),
            ("saved_query_fallback", None, timedelta(hours=12), "12hour"),
            ("neither", None, None, None),
        ]
    )
    def test_node_sync_interval_reads_target_first(
        self,
        _name: str,
        target: timedelta | None,
        saved_query_interval: timedelta | None,
        expected: str | None,
    ):
        self.saved_query.sync_frequency_interval = saved_query_interval
        self.saved_query.save(update_fields=["sync_frequency_interval"])
        if target is not None:
            set_declared_target(self.view_node, target)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["sync_interval"], expected)

    def test_run_requires_direction(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("direction", response.json()["error"])

    def test_run_rejects_invalid_direction(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "invalid"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_run_rejects_table_nodes(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.table_node.id}/run/",
            {"direction": "upstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("table", response.json()["error"].lower())

    @parameterized.expand(
        [("upstream_from_a_reader", "upstream", False), ("downstream_from_a_managed_view", "downstream", True)]
    )
    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_a_run_stays_on_the_side_of_a_managed_view_it_started_from(
        self, _name, direction, start_from_managed_view, mock_sync_connect
    ):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client
        managed_node = self._create_managed_node()
        Edge.objects.create(team=self.team, dag=self.dag, source=managed_node, target=self.view_node)
        start = managed_node if start_from_managed_view else self.view_node

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(
                f"/api/environments/{self.team.id}/data_modeling_nodes/{start.id}/run/",
                {"direction": direction},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["node_ids"], [str(start.id)])
        mock_client.start_workflow.assert_called_once()

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_run_downstream_starts_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "downstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_client.start_workflow.assert_called_once()

    def test_materialize_rejects_table_nodes(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.table_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("table", response.json()["error"].lower())

    def _suspend(self, node: Node) -> None:
        mark_node_suspended(node, engine="clickhouse", reason="boom", job_id=str(uuid4()), fingerprint=None)
        node.save()

    def test_suspended_node_reports_its_state_and_can_be_resumed(self):
        self._suspend(self.view_node)

        detail = f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/"
        self.assertEqual(self.client.get(detail).json()["suspended"]["clickhouse"]["reason"], "boom")

        response = self.client.post(f"{detail}resume/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(detail).json()["suspended"], {})

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_run_resumes_every_node_it_was_asked_to_run(self, mock_sync_connect):
        # A suspended node is skipped by ExecuteDAGWorkflow, so without this the button is a no-op.
        mock_sync_connect.return_value = AsyncMock()
        downstream = Node.objects.create(
            team=self.team,
            dag=self.dag,
            saved_query=DataWarehouseSavedQuery.objects.create(
                name="downstream_view", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
            ),
            type=NodeType.VIEW,
        )
        Edge.objects.create(team=self.team, dag=self.dag, source=self.view_node, target=downstream)
        self._suspend(self.view_node)
        self._suspend(downstream)

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "downstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.view_node.refresh_from_db()
        downstream.refresh_from_db()
        self.assertEqual(suspension_state(self.view_node), {})
        self.assertEqual(suspension_state(downstream), {})

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_materialize_resumes_the_node(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()
        self._suspend(self.view_node)

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.view_node.refresh_from_db()
        self.assertEqual(suspension_state(self.view_node), {})

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_materialization_without_resume_keeps_the_node_suspended(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client
        self._suspend(self.view_node)
        before = suspension_state(self.view_node)

        start_node_materialization(self.view_node, resume=False)

        self.view_node.refresh_from_db()
        self.assertEqual(suspension_state(self.view_node), before)
        self.assertIsNone(suspension_reset_at(self.view_node, "clickhouse"))
        self.assertEqual(mock_client.start_workflow.call_args[0][0], "data-modeling-materialize-view")

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_run_starts_the_execute_dag_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "upstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_args = mock_client.start_workflow.call_args
        self.assertEqual(call_args[0][0], "data-modeling-execute-dag")

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_materialize_starts_the_materialize_view_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_args = mock_client.start_workflow.call_args
        self.assertEqual(call_args[0][0], "data-modeling-materialize-view")
        self.assertEqual(call_args.kwargs["id"], f"materialize-view-{self.view_node.id}")
        self.assertEqual(call_args.kwargs["id_conflict_policy"], WorkflowIDConflictPolicy.USE_EXISTING)
        self.assertEqual(call_args.kwargs["id_reuse_policy"], WorkflowIDReusePolicy.ALLOW_DUPLICATE)
        self.assertEqual(call_args.kwargs["retry_policy"].maximum_attempts, 1)

    def test_lineage_returns_subgraph(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={self.view_node.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn(str(self.view_node.id), node_ids)
        self.assertIn(str(self.table_node.id), node_ids)
        edge_source_ids = {e["source_id"] for e in response.json()["edges"]}
        self.assertIn(str(self.table_node.id), edge_source_ids)

    def test_lineage_by_saved_query_id(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?saved_query_id={self.view_node.saved_query_id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn(str(self.view_node.id), node_ids)
        self.assertIn(str(self.table_node.id), node_ids)

    def test_lineage_requires_node_id_or_saved_query_id(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(["node_id", "saved_query_id", "metric_id"])
    def test_lineage_invalid_uuid_returns_400(self, lookup_param):
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?{lookup_param}=not-a-uuid"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(["node_id", "saved_query_id", "metric_id"])
    def test_lineage_does_not_leak_other_teams_nodes(self, lookup_param):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        other_saved_query = DataWarehouseSavedQuery.objects.create(
            name="other_view", team=other_team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        other_node = Node.objects.create(
            team=other_team, dag=other_dag, saved_query=other_saved_query, type=NodeType.VIEW
        )
        other_metric_node = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_metric",
            type=NodeType.METRIC,
            metric_id=uuid4(),
        )

        lookup_value = {
            "node_id": other_node.id,
            "saved_query_id": other_saved_query.id,
            "metric_id": other_metric_node.metric_id,
        }[lookup_param]
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?{lookup_param}={lookup_value}"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_lineage_multi_level(self):
        sq_b = DataWarehouseSavedQuery.objects.create(
            name="view_b", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        sq_c = DataWarehouseSavedQuery.objects.create(
            name="view_c", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        view_b = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="view_b",
            type=NodeType.VIEW,
            saved_query=sq_b,
        )
        view_c = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="view_c",
            type=NodeType.VIEW,
            saved_query=sq_c,
        )
        Edge.objects.create(team=self.team, dag=self.dag, source=self.view_node, target=view_b)
        Edge.objects.create(team=self.team, dag=self.dag, source=view_b, target=view_c)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={view_b.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn(str(self.table_node.id), node_ids)
        self.assertIn(str(self.view_node.id), node_ids)
        self.assertIn(str(view_b.id), node_ids)
        self.assertIn(str(view_c.id), node_ids)

    def test_lineage_no_dependencies(self):
        sq_standalone = DataWarehouseSavedQuery.objects.create(
            name="standalone", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        standalone = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="standalone",
            type=NodeType.VIEW,
            saved_query=sq_standalone,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={standalone.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["nodes"]), 1)
        self.assertEqual(response.json()["nodes"][0]["id"], str(standalone.id))
        self.assertEqual(len(response.json()["edges"]), 0)

    def test_lineage_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        other_table = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_table",
            type=NodeType.TABLE,
        )
        other_sq = DataWarehouseSavedQuery.objects.create(
            name="other_view", team=other_team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        other_view = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_view",
            type=NodeType.VIEW,
            saved_query=other_sq,
        )
        Edge.objects.create(
            team=other_team,
            dag=other_dag,
            source=other_table,
            target=other_view,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={self.view_node.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertNotIn(str(other_table.id), node_ids)
        self.assertNotIn(str(other_view.id), node_ids)

    @parameterized.expand(["put", "patch"])
    def test_saved_query_id_cannot_be_bound_to_other_teams_query(self, method):
        other_team = Team.objects.create(organization=self.organization)
        foreign_sq = DataWarehouseSavedQuery.objects.create(
            name="leaked_name",
            team=other_team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        original_saved_query_id = self.view_node.saved_query_id
        url = f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/"
        if method == "patch":
            response = self.client.patch(url, data={"saved_query_id": str(foreign_sq.id)}, format="json")
        else:
            response = self.client.put(
                url,
                data={
                    "name": "test_view",
                    "type": NodeType.VIEW,
                    "saved_query_id": str(foreign_sq.id),
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.view_node.refresh_from_db()
        self.assertEqual(self.view_node.saved_query_id, original_saved_query_id)
        self.assertNotEqual(self.view_node.name, foreign_sq.name)

    def _create_managed_node(self) -> Node:
        sq = DataWarehouseSavedQuery.objects.create(
            name="managed_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            managed_viewset=_managed_viewset(self.team),
        )
        return Node.objects.create(team=self.team, dag=self.dag, saved_query=sq, type=NodeType.VIEW, description="orig")

    @parameterized.expand(["node", "edge"])
    def test_deleting_the_last_reader_of_a_table_deletes_the_table_node(self, deleted):
        if deleted == "node":
            url = f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/"
        else:
            edge = Edge.objects.get(source=self.table_node, target=self.view_node)
            url = f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Node.objects.filter(id=self.table_node.id).exists())

    @parameterized.expand([("managed_view", False), ("table_a_managed_view_reads", True)])
    def test_cannot_delete_node_of_managed_view(self, _name, delete_the_table):
        managed_node = self._create_managed_node()
        Edge.objects.create(team=self.team, dag=self.dag, source=self.table_node, target=managed_node)
        node = self.table_node if delete_the_table else managed_node

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_nodes/{node.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Node.objects.filter(id=node.id).exists())

    @parameterized.expand([("flag_off", False), ("flag_on", True)])
    def test_managed_view_nodes_show_only_with_the_managed_viewsets_flag(self, _name, flag_enabled):
        managed_node = self._create_managed_node()
        Edge.objects.create(team=self.team, dag=self.dag, source=self.table_node, target=managed_node)

        with patch("posthoganalytics.feature_enabled", return_value=flag_enabled):
            list_response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")
            lineage_response = self.client.get(
                f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={self.table_node.id}"
            )
            detail_response = self.client.get(
                f"/api/environments/{self.team.id}/data_modeling_nodes/{managed_node.id}/"
            )

        listed_ids = {node["id"] for node in list_response.json()["results"]}
        lineage = lineage_response.json()
        lineage_ids = {node["id"] for node in lineage["nodes"]}
        self.assertEqual(str(managed_node.id) in listed_ids, flag_enabled)
        self.assertIn(str(self.table_node.id), listed_ids)
        self.assertEqual(str(managed_node.id) in lineage_ids, flag_enabled)
        self.assertEqual(len(lineage["edges"]), 2 if flag_enabled else 1)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK if flag_enabled else status.HTTP_404_NOT_FOUND)

    def test_cannot_patch_node_of_managed_view(self):
        node = self._create_managed_node()

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/data_modeling_nodes/{node.id}/",
                data={"description": "changed"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        node.refresh_from_db()
        self.assertEqual(node.description, "orig")


class TestMetricNodeAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name=f"posthog_{self.team.id}")
        self.table_node = Node.objects.create(team=self.team, dag=self.dag, name="events", type=NodeType.TABLE)
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            name="accounts", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        self.view_node = Node.objects.create(
            team=self.team, dag=self.dag, saved_query=self.saved_query, type=NodeType.VIEW
        )
        self.metric_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="weekly_active_accounts",
            type=NodeType.METRIC,
            metric_id=uuid4(),
        )
        Edge.objects.create(team=self.team, dag=self.dag, source=self.table_node, target=self.view_node)
        Edge.objects.create(team=self.team, dag=self.dag, source=self.view_node, target=self.metric_node)
        self.url = f"/api/environments/{self.team.id}/data_modeling_nodes/"

    def test_list_serializes_the_metric_reference(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        serialized = next(node for node in response.json()["results"] if node["id"] == str(self.metric_node.id))
        self.assertEqual(serialized["type"], NodeType.METRIC)
        self.assertEqual(serialized["metric_id"], str(self.metric_node.metric_id))
        self.assertIsNone(serialized["lineage_issue"])

    @parameterized.expand(
        [
            ("sync_failed", {"degraded_sync": {"error": "boom", "at": "2026-09-15T00:00:00Z"}}, "boom"),
            ("unresolved", {"unresolved": {"names": ["gone", "also_gone"], "at": None}}, "gone, also_gone"),
        ]
    )
    def test_list_reports_a_lineage_issue(self, kind, system, expected_detail):
        self.metric_node.properties = {"system": system}
        self.metric_node.save()

        response = self.client.get(self.url)

        serialized = next(node for node in response.json()["results"] if node["id"] == str(self.metric_node.id))
        self.assertEqual(serialized["lineage_issue"]["kind"], kind)
        self.assertEqual(serialized["lineage_issue"]["detail"], expected_detail)

    def test_lineage_by_metric_id_returns_the_upstream_view_and_table(self):
        response = self.client.get(f"{self.url}lineage/?metric_id={self.metric_node.metric_id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {node["id"] for node in response.json()["nodes"]}
        self.assertEqual(node_ids, {str(self.metric_node.id), str(self.view_node.id), str(self.table_node.id)})

    @parameterized.expand(["run", "materialize"])
    def test_a_metric_node_cannot_be_executed(self, action):
        response = self.client.post(f"{self.url}{self.metric_node.id}/{action}/", {"direction": "upstream"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("metric", response.json()["error"].lower())

    def test_a_metric_node_cannot_be_deleted_through_the_api(self):
        response = self.client.delete(f"{self.url}{self.metric_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Node.objects.filter(id=self.metric_node.id).exists())

    def test_a_metric_node_cannot_be_retyped_to_table(self):
        # metric_id is read-only, so a retype to table would leave it set and reach
        # node_backing_reference_matches_type as an uncaught IntegrityError.
        response = self.client.patch(f"{self.url}{self.metric_node.id}/", data={"type": NodeType.TABLE}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.metric_node.refresh_from_db()
        self.assertEqual(self.metric_node.type, NodeType.METRIC)

    @parameterized.expand(["name", "description"])
    def test_a_metric_node_cannot_be_updated_through_the_api(self, field):
        before = getattr(self.metric_node, field)

        response = self.client.patch(f"{self.url}{self.metric_node.id}/", data={field: "changed"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.metric_node.refresh_from_db()
        self.assertEqual(getattr(self.metric_node, field), before)

    def test_an_edge_into_a_metric_node_cannot_be_deleted_through_the_api(self):
        edge = Edge.objects.get(target=self.metric_node)

        response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Edge.objects.filter(id=edge.id).exists())

    @parameterized.expand(
        [
            ("node", "data_modeling_nodes", {"name": "sneaky", "type": NodeType.TABLE}),
            ("edge", "data_modeling_edges", {"properties": {}}),
        ]
    )
    def test_nodes_and_edges_cannot_be_created_through_the_api(self, _name, endpoint, payload):
        nodes_before, edges_before = Node.objects.count(), Edge.objects.count()

        response = self.client.post(f"/api/environments/{self.team.id}/{endpoint}/", data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual((Node.objects.count(), Edge.objects.count()), (nodes_before, edges_before))

    def test_a_node_cannot_be_retyped_through_the_api(self):
        response = self.client.patch(f"{self.url}{self.table_node.id}/", data={"type": NodeType.VIEW}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.table_node.refresh_from_db()
        self.assertEqual(self.table_node.type, NodeType.TABLE)


@pytest.mark.ee
class TestMetricNodeVisibility(WarehouseAccessControlTestMixin):
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name=f"posthog_{self.team.id}")
        self.view_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            saved_query=DataWarehouseSavedQuery.objects.create(
                name="accounts", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
            ),
            type=NodeType.VIEW,
        )
        self.metric_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="weekly_active_accounts",
            type=NodeType.METRIC,
            metric_id=uuid4(),
        )
        self.edge = Edge.objects.create(team=self.team, dag=self.dag, source=self.view_node, target=self.metric_node)
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

    def _catalog_access(self, access_level: str) -> None:
        if access_level == "none":
            self._create_project_default(resource="data_catalog", access_level="none")
        else:
            self._create_access_control(self.viewer_user, resource="data_catalog", access_level=access_level)

    @parameterized.expand(
        [
            ("nodes_hidden", "none", False),
            ("nodes_visible", "viewer", True),
        ]
    )
    def test_nodes_are_visible_only_with_catalog_access(self, _name, catalog_access, expected_visible):
        self._catalog_access(catalog_access)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        node_ids = {node["id"] for node in response.json()["results"]}
        self.assertEqual(str(self.metric_node.id) in node_ids, expected_visible)
        self.assertIn(str(self.view_node.id), node_ids)

    @parameterized.expand(
        [
            ("edges_hidden", "none", False),
            ("edges_visible", "viewer", True),
        ]
    )
    def test_edges_are_visible_only_with_catalog_access(self, _name, catalog_access, expected_visible):
        self._catalog_access(catalog_access)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        edges = {edge["id"]: edge for edge in response.json()["results"]}
        self.assertEqual(str(self.edge.id) in edges, expected_visible)
        if expected_visible:
            self.assertEqual(
                edges[str(self.edge.id)],
                {"id": str(self.edge.id), "source_id": str(self.edge.source_id), "target_id": str(self.edge.target_id)},
            )

    @parameterized.expand(
        [
            ("counts_hidden", "none", 0),
            ("counts_visible", "viewer", 1),
        ]
    )
    def test_downstream_count_never_reports_a_metric_the_reader_cannot_see(self, _name, catalog_access, expected):
        self._catalog_access(catalog_access)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        view = next(node for node in response.json()["results"] if node["id"] == str(self.view_node.id))
        self.assertEqual(view["downstream_count"], expected)

    @parameterized.expand(
        [
            ("lineage_hidden", "none", False),
            ("lineage_visible", "viewer", True),
        ]
    )
    def test_lineage_shows_metric_nodes_only_with_catalog_access(self, _name, catalog_access, expected_visible):
        self._catalog_access(catalog_access)

        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={self.view_node.id}"
        )

        payload = response.json()
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertEqual(str(self.metric_node.id) in node_ids, expected_visible)
        self.assertEqual(len(payload["edges"]) == 1, expected_visible)


@pytest.mark.ee
class TestNodeAccessControl(WarehouseAccessControlTestMixin):
    # NodeViewSet is scope_object = "INTERNAL", so AccessControlPermission does not gate it on any
    # resource — the actions re-apply warehouse RBAC by hand. warehouse_view inherits from
    # warehouse_objects, so grant at the umbrella.
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name=f"posthog_{self.team.id}")
        self.node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            saved_query=DataWarehouseSavedQuery.objects.create(
                name="suspended_view", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
            ),
            type=NodeType.VIEW,
        )
        mark_node_suspended(self.node, engine="clickhouse", reason="boom", job_id=str(uuid4()), fingerprint=None)
        self.node.save()

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.id}/data_modeling_nodes/"

    @parameterized.expand(
        [
            ("viewer", status.HTTP_403_FORBIDDEN),
            ("editor", status.HTTP_200_OK),
        ]
    )
    def test_resume_requires_warehouse_write_access(self, access_level, expected_status):
        user = self.viewer_user if access_level == "viewer" else self.editor_user
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        response = self.client.post(f"{self._list_url()}{self.node.id}/resume/")

        self.assertEqual(response.status_code, expected_status)
        self.node.refresh_from_db()
        self.assertEqual(suspension_state(self.node) == {}, expected_status == status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("node_viewer", "node", "viewer", status.HTTP_403_FORBIDDEN),
            ("node_editor", "node", "editor", status.HTTP_204_NO_CONTENT),
            ("edge_viewer", "edge", "viewer", status.HTTP_403_FORBIDDEN),
            ("edge_editor", "edge", "editor", status.HTTP_204_NO_CONTENT),
        ]
    )
    def test_deleting_requires_warehouse_write_access(self, _name, deleted, access_level, expected_status):
        source = Node.objects.create(team=self.team, dag=self.dag, name="events", type=NodeType.TABLE)
        edge = Edge.objects.create(team=self.team, dag=self.dag, source=source, target=self.node)
        user = self.viewer_user if access_level == "viewer" else self.editor_user
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)
        target: Node | Edge = self.node if deleted == "node" else edge
        if deleted == "node":
            url = f"{self._list_url()}{self.node.id}/"
        else:
            url = f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(
            type(target).objects.filter(pk=target.pk).exists(), expected_status == status.HTTP_403_FORBIDDEN
        )

    @parameterized.expand(
        [
            ("list_granted", False, "viewer", status.HTTP_200_OK),
            ("list_denied", False, None, status.HTTP_403_FORBIDDEN),
            ("retrieve_granted", True, "viewer", status.HTTP_200_OK),
            ("retrieve_denied", True, None, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_reading_nodes_requires_warehouse_read_access(self, _name, detail, access_level, expected_status):
        # The serialized `suspended` state carries the raw materialization error, so a project member
        # denied warehouse access must not be able to read nodes at all.
        if access_level is None:
            self._create_project_default(access_level="none")
        else:
            self._create_access_control(self.viewer_user, access_level=access_level)
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"{self._list_url()}{self.node.id}/" if detail else self._list_url())

        self.assertEqual(response.status_code, expected_status)


class TestEdgeViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag_id = f"posthog_{self.team.id}"
        self.dag = DAG.objects.create(team=self.team, name=self.dag_id)

        self.source_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="events",
            type=NodeType.TABLE,
        )

        self.saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        self.target_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            saved_query=self.saved_query,
            type=NodeType.VIEW,
        )

        self.edge = Edge.objects.create(
            team=self.team,
            dag=self.dag,
            source=self.source_node,
            target=self.target_node,
        )

    def test_list_edges(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        edge = response.json()["results"][0]
        self.assertEqual(edge["source_id"], str(self.source_node.id))
        self.assertEqual(edge["target_id"], str(self.target_node.id))

    def test_list_edges_query_count_does_not_grow_with_edges(self):
        url = f"/api/environments/{self.team.id}/data_modeling_edges/"
        self.client.get(url)
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(url)

        for i in range(5):
            target = Node.objects.create(team=self.team, dag=self.dag, name=f"table_{i}", type=NodeType.TABLE)
            Edge.objects.create(team=self.team, dag=self.dag, source=self.source_node, target=target)

        with CaptureQueriesContext(connection) as grown:
            response = self.client.get(url)

        self.assertEqual(response.json()["count"], 6)
        self.assertEqual(len(grown.captured_queries), len(baseline.captured_queries))

    def test_list_edges_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        other_source = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_events",
            type=NodeType.TABLE,
        )
        other_target = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_view",
            type=NodeType.TABLE,
        )
        Edge.objects.create(
            team=other_team,
            dag=other_dag,
            source=other_source,
            target=other_target,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def _create_managed_edge(self) -> Edge:
        dag = DAG.get_or_create_default(self.team)
        source = Node.objects.create(team=self.team, dag=dag, name="m_events", type=NodeType.TABLE)
        sq = DataWarehouseSavedQuery.objects.create(
            name="m_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            managed_viewset=_managed_viewset(self.team),
        )
        target = Node.objects.create(team=self.team, dag=dag, saved_query=sq, type=NodeType.VIEW)
        return Edge.objects.create(team=self.team, dag=dag, source=source, target=target, properties={"a": 1})

    def test_cannot_delete_edge_into_managed_view(self):
        edge = self._create_managed_edge()

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Edge.objects.filter(id=edge.id).exists())

    def test_cannot_patch_edge_into_managed_view(self):
        edge = self._create_managed_edge()

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/",
                data={"properties": {"a": 2}},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        edge.refresh_from_db()
        self.assertEqual(edge.properties, {"a": 1})
