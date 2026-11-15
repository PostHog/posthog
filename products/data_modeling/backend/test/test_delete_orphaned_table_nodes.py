from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType


class TestDeleteOrphanedTableNodes(BaseTest):
    def test_only_apply_deletes_and_only_table_nodes_nothing_reads(self):
        view = DataWarehouseSavedQuery.objects.create(
            name="reads_events", team=self.team, query={"query": "SELECT * FROM events", "kind": "HogQLQuery"}
        )
        sync_saved_query_to_dag(view)
        orphan = Node.objects.create(
            team=self.team, dag=DAG.get_or_create_default(self.team), name="dropped_table", type=NodeType.TABLE
        )

        call_command("delete_orphaned_table_nodes", team_id=self.team.pk, stdout=StringIO())
        self.assertTrue(Node.objects.filter(id=orphan.id).exists())

        call_command("delete_orphaned_table_nodes", team_id=self.team.pk, apply=True, stdout=StringIO())
        self.assertFalse(Node.objects.filter(id=orphan.id).exists())
        self.assertTrue(Node.objects.filter(team=self.team, name="events", type=NodeType.TABLE).exists())
        self.assertTrue(Node.objects.filter(saved_query=view).exists())
