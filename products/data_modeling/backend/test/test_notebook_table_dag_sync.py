from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_modeling.backend.logic.notebook_table_dag_sync import (
    delete_notebook_table_node,
    sync_notebook_table_to_dag,
)
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import Edge, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import DEGRADED_SYNC_KEY, NOTEBOOK_SOURCE_KEY, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestSyncNotebookTableToDag(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.table = DataWarehouseTable.objects.create(team=self.team, name="scores", format="Parquet")

    def _sync(self, *queries: str) -> None:
        sync_notebook_table_to_dag(self.team.id, "scores", str(self.table.id), list(queries), "nb123", "cell-1")

    def _node(self) -> Node:
        return Node.objects.get(team=self.team, name="scores", type=NodeType.TABLE)

    def _view(self, name: str, query: str) -> DataWarehouseSavedQuery:
        view = DataWarehouseSavedQuery.objects.create(
            name=name, team=self.team, query={"query": query, "kind": "HogQLQuery"}
        )
        sync_saved_query_to_dag(view)
        return view

    def test_table_keeps_upstream_and_downstream_edges(self):
        self._view("accounts", "SELECT distinct_id FROM events")

        self._sync("SELECT event FROM events", "SELECT * FROM accounts", "SELECT * FROM scores")

        node = self._node()
        self.assertEqual(node.properties[NOTEBOOK_SOURCE_KEY], {"short_id": "nb123", "node_id": "cell-1"})
        upstream = {edge.source.name for edge in Edge.objects.filter(target=node).select_related("source")}
        self.assertEqual(upstream, {"events", "accounts"})

        reader = self._view("top_scores", "SELECT * FROM scores")
        self.assertTrue(Edge.objects.filter(source=node, target__saved_query=reader).exists())

        reader.query = {"query": "SELECT 1", "kind": "HogQLQuery"}
        reader.save()
        sync_saved_query_to_dag(reader)
        self.assertEqual(Edge.objects.filter(target=self._node()).count(), 2)

    def test_cycle_marks_the_node_and_keeps_the_last_edges(self):
        self._sync("SELECT event FROM events")
        self._view("top_scores", "SELECT * FROM scores")

        self._sync("SELECT * FROM top_scores")

        node = self._node()
        self.assertIn(DEGRADED_SYNC_KEY, node.properties["system"])
        self.assertEqual(
            {edge.source.name for edge in Edge.objects.filter(target=node).select_related("source")}, {"events"}
        )

    @parameterized.expand([("no_reader", False), ("read_by_a_view", True)])
    def test_deleting_the_table_drops_its_notebook_lineage(self, _name: str, has_reader: bool):
        self._sync("SELECT event FROM events")
        if has_reader:
            reader = self._view("top_scores", "SELECT * FROM scores")

        delete_notebook_table_node(self.team.id, str(self.table.id))

        nodes = Node.objects.filter(team=self.team, name="scores", type=NodeType.TABLE)
        self.assertEqual(nodes.exists(), has_reader)
        self.assertFalse(Node.objects.filter(team=self.team, name="events").exists())
        if has_reader:
            node = nodes.get()
            self.assertNotIn(NOTEBOOK_SOURCE_KEY, node.properties)
            self.assertFalse(Edge.objects.filter(target=node).exists())
            self.assertTrue(Edge.objects.filter(source=node, target__saved_query=reader).exists())
