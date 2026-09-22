from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from posthog.hogql.database.database import Database

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
from products.data_modeling.backend.logic.metric_dag_sync import (
    delete_metric_node,
    mark_metric_node_degraded,
    sync_metric_to_dag,
)
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import Edge, Node
from products.data_modeling.backend.models.dag import DAG, DEFAULT_DAG_NAME
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import DEGRADED_SYNC_KEY, UNRESOLVED_DEPENDENCIES_KEY, NodeType


@pytest.mark.django_db
class TestSyncMetricToDag(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.metric_id = uuid4()

    def _view(self, name: str, query: str = "SELECT * FROM events") -> DataWarehouseSavedQuery:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=name, team=self.team, query={"query": query, "kind": "HogQLQuery"}
        )
        sync_saved_query_to_dag(saved_query)
        return saved_query

    def _node(self) -> Node:
        return Node.objects.get(team=self.team, metric_id=self.metric_id)

    def _sources(self) -> set[str]:
        return {edge.source.name for edge in Edge.objects.filter(target=self._node()).select_related("source")}

    def test_sync_creates_a_leaf_node_in_the_default_dag(self):
        self._view("accounts_view")

        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", ["events", "accounts_view"])

        node = self._node()
        self.assertEqual(node.type, NodeType.METRIC)
        self.assertEqual(node.name, "weekly_active_accounts")
        self.assertEqual(node.dag.name, DEFAULT_DAG_NAME)
        self.assertEqual(self._sources(), {"events", "accounts_view"})
        self.assertFalse(Edge.objects.filter(source=node).exists())

    def test_resync_replaces_edges_and_follows_a_rename(self):
        self._view("accounts_view")
        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", ["events"])

        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_teams", ["accounts_view"])

        self.assertEqual(self._node().name, "weekly_active_teams")
        self.assertEqual(self._sources(), {"accounts_view"})
        self.assertEqual(Node.objects.filter(team=self.team, type=NodeType.METRIC).count(), 1)

    def test_an_unresolvable_name_is_skipped_and_recorded(self):
        unresolved = sync_metric_to_dag(
            self.team, self.metric_id, "weekly_active_accounts", ["events", "table_that_went_away"]
        )

        self.assertEqual(unresolved, ["table_that_went_away"])
        self.assertEqual(self._sources(), {"events"})
        marker = self._node().properties["system"][UNRESOLVED_DEPENDENCIES_KEY]
        self.assertEqual(marker["names"], ["table_that_went_away"])

    def test_a_view_renamed_after_the_schema_was_built_is_skipped_not_fatal(self):
        saved_query = self._view("accounts_view")
        database = Database.create_for(
            team=self.team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )
        saved_query.name = "accounts_view_v2"
        saved_query.save()

        sync_metric_to_dag(
            self.team,
            self.metric_id,
            "weekly_active_accounts",
            ["events", "accounts_view"],
            database=database,
        )

        self.assertEqual(self._sources(), {"events"})
        marker = self._node().properties["system"][UNRESOLVED_DEPENDENCIES_KEY]
        self.assertEqual(marker["names"], ["accounts_view"])

    def test_a_later_clean_sync_clears_the_unresolved_marker(self):
        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", ["table_that_went_away"])

        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", ["events"])

        self.assertNotIn("system", self._node().properties)

    def test_a_metric_over_a_managed_view_reaches_it_through_a_proxy_table_node(self):
        managed_dag = DAG.get_or_create_revenue_analytics(self.team)
        managed_query = DataWarehouseSavedQuery.objects.create(
            name="revenue_view", team=self.team, query={"query": "SELECT * FROM events", "kind": "HogQLQuery"}
        )
        sync_saved_query_to_dag(managed_query, dag=managed_dag, allow_managed=True)

        sync_metric_to_dag(self.team, self.metric_id, "mrr", ["revenue_view"])

        default_dag = DAG.objects.get(team=self.team, name=DEFAULT_DAG_NAME)
        proxy = Node.objects.get(team=self.team, dag=default_dag, name="revenue_view")
        self.assertEqual(proxy.type, NodeType.TABLE)
        self.assertEqual(proxy.properties["origin"], "cross_dag_view")
        self.assertTrue(Edge.objects.filter(source=proxy, target=self._node()).exists())

    def test_a_metric_can_share_a_name_with_the_table_it_reads(self):
        sync_metric_to_dag(self.team, self.metric_id, "events", ["events"])

        self.assertEqual(self._sources(), {"events"})
        self.assertEqual(Node.objects.filter(team=self.team, name="events").count(), 2)

    def test_a_passed_database_is_reused_instead_of_building_one(self):
        with mock.patch("products.data_modeling.backend.logic.metric_dag_sync.Database") as database_class:
            sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", [], database=mock.Mock())

        database_class.create_for.assert_not_called()

    def test_delete_removes_the_node_and_its_edges(self):
        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", ["events"])
        node_id = self._node().id

        delete_metric_node(self.team, self.metric_id)

        self.assertFalse(Node.objects.filter(id=node_id).exists())
        self.assertFalse(Edge.objects.filter(target_id=node_id).exists())

    def test_a_failed_sync_is_recorded_on_the_node_and_cleared_by_the_next_one(self):
        mark_metric_node_degraded(self.team, self.metric_id, "weekly_active_accounts", "schema build blew up")

        self.assertEqual(
            self._node().properties["system"][DEGRADED_SYNC_KEY]["error"],
            "schema build blew up",
        )

        sync_metric_to_dag(self.team, self.metric_id, "weekly_active_accounts", ["events"])

        self.assertNotIn("system", self._node().properties)

    def test_a_failed_marker_write_leaves_no_unmarked_node(self):
        with mock.patch.object(Node, "mark_lineage_sync_failed", side_effect=RuntimeError("postgres went away")):
            with self.assertRaises(RuntimeError):
                mark_metric_node_degraded(self.team, self.metric_id, "weekly_active_accounts", "schema build blew up")

        self.assertFalse(Node.objects.filter(team=self.team, metric_id=self.metric_id).exists())
