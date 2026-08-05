from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import get_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import temporal_listing as _temporal_listing

H6 = timedelta(hours=6)

RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"
COMMAND = "products.data_modeling.backend.management.commands.reconcile_freshness_schedules"


@pytest.mark.django_db
class TestReconcileFreshnessSchedules(BaseTest):
    def _legacy_dag(self) -> tuple[DAG, Node]:
        dag = DAG.objects.create(team=self.team, name="Default", sync_frequency_interval=H6)
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="v",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=H6,
        )
        node = Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.VIEW)
        return dag, node

    def test_converts_legacy_dag_seeding_targets_first(self):
        dag, node = self._legacy_dag()
        legacy_id = str(dag.id)

        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.delete_schedule"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_temporal_listing([legacy_id]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            call_command("reconcile_freshness_schedules", "--team-id", str(self.team.pk), stdout=StringIO())

        node.refresh_from_db()
        self.assertEqual(get_declared_target(node), H6)
        assert node.saved_query is not None
        node.saved_query.refresh_from_db()
        self.assertIsNone(node.saved_query.sync_frequency_interval)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(legacy_id, H6))
        delete.assert_called_once_with(mock.ANY, schedule_id=legacy_id)

    def test_refuses_unflagged_team(self):
        self._legacy_dag()
        with mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=False):
            with self.assertRaisesRegex(CommandError, "tiered-schedules flag"):
                call_command("reconcile_freshness_schedules", "--team-id", str(self.team.pk), stdout=StringIO())

    def test_sweeps_live_v1_schedules(self):
        dag, node = self._legacy_dag()
        assert node.saved_query is not None
        v1_id = str(node.saved_query.id)

        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.delete_schedule") as delete_v1,
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            call_command("reconcile_freshness_schedules", "--team-id", str(self.team.pk), stdout=StringIO())

        delete_v1.assert_called_once_with(mock.ANY, schedule_id=v1_id)
        node.saved_query.refresh_from_db()
        self.assertIsNone(node.saved_query.sync_frequency_interval)

    def test_dry_run_rejects_default_interval(self):
        self._legacy_dag()
        with self.assertRaisesRegex(CommandError, "default-interval-seconds"):
            call_command(
                "reconcile_freshness_schedules",
                "--team-id",
                str(self.team.pk),
                "--dry-run",
                "--default-interval-seconds",
                "3600",
                stdout=StringIO(),
            )

    def test_query_in_two_dags_seeds_from_its_own_interval(self):
        D1 = timedelta(days=1)
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="shared",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=H6,
        )
        dag_a = DAG.objects.create(team=self.team, name="A", sync_frequency_interval=D1)
        dag_b = DAG.objects.create(team=self.team, name="B", sync_frequency_interval=D1)
        node_a = Node.objects.create(team=self.team, dag=dag_a, saved_query=saved_query, type=NodeType.VIEW)
        node_b = Node.objects.create(team=self.team, dag=dag_b, saved_query=saved_query, type=NodeType.VIEW)

        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.delete_schedule"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            call_command("reconcile_freshness_schedules", "--team-id", str(self.team.pk), stdout=StringIO())

        node_a.refresh_from_db()
        node_b.refresh_from_db()
        self.assertEqual(get_declared_target(node_a), H6)
        self.assertEqual(get_declared_target(node_b), H6)

    def test_dry_run_delegates_to_preview_and_writes_nothing(self):
        dag, node = self._legacy_dag()

        out = StringIO()
        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            call_command("reconcile_freshness_schedules", "--team-id", str(self.team.pk), "--dry-run", stdout=out)

        node.refresh_from_db()
        self.assertIsNone(get_declared_target(node))
        assert node.saved_query is not None
        node.saved_query.refresh_from_db()
        self.assertEqual(node.saved_query.sync_frequency_interval, H6)
        create.assert_not_called()
        delete.assert_not_called()
        self.assertIn("dry run", out.getvalue())
