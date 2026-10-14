from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.data_modeling.backend.logic.node_frequency import get_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import LineageIssueKind, Node

COMMAND = "products.data_modeling.backend.management.commands.backfill_saved_query_nodes"


class TestBackfillSavedQueryNodes(BaseTest):
    def _view(
        self, name: str, sql: str, is_materialized: bool = False, interval: timedelta | None = None
    ) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": sql},
            is_materialized=is_materialized,
            sync_frequency_interval=interval,
        )

    def test_gives_every_nodeless_view_a_node_only_when_applied(self) -> None:
        downstream = self._view("downstream_view", "SELECT event FROM upstream_view")
        upstream = self._view("upstream_view", "SELECT event FROM events")
        broken = self._view("broken_view", "SELECT 1 FROM no_such_table")
        materialized = self._view("materialized_view", "SELECT event FROM events", is_materialized=True)
        legacy_cadence = self._view(
            "legacy_cadence_view", "SELECT event FROM events", is_materialized=True, interval=timedelta(minutes=5)
        )

        with patch(f"{COMMAND}.reconcile_dag_schedules") as reconcile:
            call_command("backfill_saved_query_nodes")
            self.assertFalse(Node.objects.filter(team=self.team).exists())

            call_command("backfill_saved_query_nodes", "--apply")

        reconcile.assert_called_once_with(DAG.get_or_create_default(self.team), require_tiered=True)
        upstream_node = Node.objects.get(saved_query=upstream)
        downstream_node = Node.objects.get(saved_query=downstream)
        self.assertTrue(Edge.objects.filter(source=upstream_node, target=downstream_node).exists())
        broken_node = Node.objects.get(saved_query=broken)
        self.assertFalse(Edge.objects.filter(target=broken_node).exists())
        assert broken_node.lineage_issue is not None
        self.assertEqual(broken_node.lineage_issue["kind"], LineageIssueKind.SYNC_FAILED)
        self.assertEqual(get_declared_target(Node.objects.get(saved_query=materialized)), timedelta(days=1))
        self.assertEqual(get_declared_target(Node.objects.get(saved_query=legacy_cadence)), timedelta(minutes=15))
        self.assertIsNone(get_declared_target(upstream_node))
