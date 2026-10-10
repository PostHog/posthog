from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import Edge, Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType
from products.product_analytics.backend.facade.models import Insight


class TestBackfillInsightLineage(BaseTest):
    def _insight(self, name: str, sql: str, deleted: bool = False) -> Insight:
        return Insight.objects.create(
            team=self.team,
            name=name,
            deleted=deleted,
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": sql}},
        )

    def _insight_node(self, insight: Insight) -> Node:
        return Node.objects.create(
            team=self.team,
            dag=DAG.get_or_create_default(self.team),
            name=insight.name or insight.short_id,
            type=NodeType.INSIGHT,
            insight_id=insight.id,
        )

    def _backfill(self) -> None:
        call_command("backfill_insight_lineage", "--team-id", str(self.team.pk), stdout=StringIO())

    def _readers(self) -> dict[int | None, set[str]]:
        return {
            node.insight_id: {edge.source.name for edge in Edge.objects.filter(target=node).select_related("source")}
            for node in Node.objects.filter(team=self.team, type=NodeType.INSIGHT)
        }

    def test_backfill_records_readers_drops_stale_nodes_and_is_idempotent(self):
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders_view", query={"kind": "HogQLQuery", "query": "SELECT event FROM events"}
        )
        view_node = sync_saved_query_to_dag(view)
        assert view_node is not None
        # Insights may share a name, so their nodes must not collide on it.
        first = self._insight("Revenue", "SELECT * FROM orders_view")
        second = self._insight("Revenue", "SELECT * FROM orders_view JOIN events ON events.event = orders_view.event")
        self._insight("Pageviews", "SELECT count() FROM events")
        stale = self._insight_node(self._insight("Old revenue", "SELECT * FROM orders_view", deleted=True))
        Edge.objects.create(team=self.team, dag=view_node.dag, source=view_node, target=stale)

        self._backfill()
        node_ids = set(Node.objects.filter(team=self.team, type=NodeType.INSIGHT).values_list("id", flat=True))
        self._backfill()

        self.assertEqual(self._readers(), {first.id: {"orders_view"}, second.id: {"orders_view"}})
        self.assertEqual(
            set(Node.objects.filter(team=self.team, type=NodeType.INSIGHT).values_list("id", flat=True)), node_ids
        )

    def test_a_team_without_views_or_warehouse_tables_keeps_no_insight_nodes(self):
        self._insight_node(self._insight("Revenue", "SELECT * FROM orders_view"))

        self._backfill()

        self.assertEqual(self._readers(), {})
