from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType


class TestDeleteDeletedSavedQueryNodes(BaseTest):
    def _view(self, name: str, sql: str) -> DataWarehouseSavedQuery:
        view = DataWarehouseSavedQuery.objects.create(
            name=name, team=self.team, query={"query": sql, "kind": "HogQLQuery"}
        )
        sync_saved_query_to_dag(view)
        return view

    def test_only_apply_deletes_and_only_nodes_of_deleted_saved_queries(self):
        live_view = self._view("reads_events", "SELECT * FROM events")
        deleted_view = self._view("reads_persons", "SELECT * FROM persons")
        DataWarehouseSavedQuery.objects.filter(id=deleted_view.id).update(deleted=True)

        call_command("delete_deleted_saved_query_nodes", team_id=self.team.pk, stdout=StringIO())
        self.assertTrue(Node.objects.filter(saved_query=deleted_view).exists())

        call_command("delete_deleted_saved_query_nodes", team_id=self.team.pk, apply=True, stdout=StringIO())
        self.assertFalse(Node.objects.filter(saved_query=deleted_view).exists())
        self.assertFalse(Node.objects.filter(team=self.team, name="persons", type=NodeType.TABLE).exists())
        self.assertTrue(Node.objects.filter(saved_query=live_view).exists())
        self.assertTrue(Node.objects.filter(team=self.team, name="events", type=NodeType.TABLE).exists())
