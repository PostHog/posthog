from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import Edge, Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

MANAGED_VIEWSETS_FLAG = "managed-viewsets"


@patch(
    "posthog.hogql.database.database.feature_enabled_or_false",
    side_effect=lambda flag, *args, **kwargs: flag == MANAGED_VIEWSETS_FLAG,
)
class TestRepointManagedViewReaders(BaseTest):
    def _managed_view(self, name: str, sql: str, viewset: DataWarehouseManagedViewSet) -> DataWarehouseSavedQuery:
        view = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": sql, "kind": "HogQLQuery"},
            columns={"event": "String"},
            managed_viewset=viewset,
        )
        sync_saved_query_to_dag(view, dag=DAG.get_or_create_revenue_analytics(self.team), allow_managed=True)
        return view

    def test_only_apply_moves_readers_to_the_reference_and_deletes_the_copies(self, _flag):
        viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        charges = self._managed_view("revenue_charges", "SELECT event FROM events", viewset)
        mrr = self._managed_view("revenue_mrr", "SELECT event FROM revenue_charges", viewset)
        managed_dag = DAG.get_or_create_revenue_analytics(self.team)
        managed_node_ids = set(Node.objects.filter(dag=managed_dag).values_list("id", flat=True))

        default_dag = DAG.get_or_create_default(self.team)
        charges_copy = Node.objects.create(team=self.team, dag=default_dag, saved_query=charges, type=NodeType.MAT_VIEW)
        mrr_copy = Node.objects.create(team=self.team, dag=default_dag, saved_query=mrr, type=NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=default_dag, source=charges_copy, target=mrr_copy)
        user_view = DataWarehouseSavedQuery.objects.create(
            name="user_view", team=self.team, query={"query": "SELECT * FROM revenue_charges", "kind": "HogQLQuery"}
        )
        user_node = Node.objects.create(team=self.team, dag=default_dag, saved_query=user_view, type=NodeType.VIEW)
        Edge.objects.create(team=self.team, dag=default_dag, source=charges_copy, target=user_node)

        call_command("repoint_managed_view_readers", team_id=self.team.pk, stdout=StringIO())
        self.assertEqual(Node.objects.filter(id__in=[charges_copy.id, mrr_copy.id]).count(), 2)

        call_command("repoint_managed_view_readers", team_id=self.team.pk, apply=True, stdout=StringIO())

        self.assertFalse(Node.objects.filter(id__in=[charges_copy.id, mrr_copy.id]).exists())
        reference = Edge.objects.get(target=user_node).source
        self.assertEqual(reference.type, NodeType.TABLE)
        self.assertEqual(reference.properties["origin"], "cross_dag_view")
        self.assertEqual(set(Node.objects.filter(dag=managed_dag).values_list("id", flat=True)), managed_node_ids)
