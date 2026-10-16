from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models import DataModelingJob, DataModelingJobStatus, Edge, Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

MANAGED_VIEWSETS_FLAG = "managed-viewsets"


class TestRepointManagedViewReaders(BaseTest):
    def setUp(self):
        super().setUp()
        flag_patch = patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: flag == MANAGED_VIEWSETS_FLAG,
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

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

    @parameterized.expand(
        [
            ("idle", False, False),
            ("charges_materializing", True, False),
            ("reader_fails_to_sync", False, True),
        ]
    )
    def test_only_apply_moves_readers_to_the_reference_and_deletes_the_copies(
        self, _name: str, charges_materializing: bool, reader_fails: bool
    ):
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
            name="user_view",
            team=self.team,
            query={"query": "" if reader_fails else "SELECT * FROM revenue_charges", "kind": "HogQLQuery"},
        )
        user_node = Node.objects.create(team=self.team, dag=default_dag, saved_query=user_view, type=NodeType.VIEW)
        Edge.objects.create(team=self.team, dag=default_dag, source=charges_copy, target=user_node)
        DataModelingJob.objects.create(team=self.team, saved_query=None, status=DataModelingJobStatus.RUNNING)
        if charges_materializing:
            DataModelingJob.objects.create(team=self.team, saved_query=charges, status=DataModelingJobStatus.RUNNING)

        call_command("repoint_managed_view_readers", team_id=self.team.pk, stdout=StringIO())
        self.assertEqual(Node.objects.filter(id__in=[charges_copy.id, mrr_copy.id]).count(), 2)

        call_command("repoint_managed_view_readers", team_id=self.team.pk, apply=True, stdout=StringIO())

        remaining = set(Node.objects.filter(id__in=[charges_copy.id, mrr_copy.id]).values_list("id", flat=True))
        self.assertEqual(remaining, {charges_copy.id} if charges_materializing or reader_fails else set())
        user_source = Edge.objects.get(target=user_node).source
        if reader_fails:
            self.assertEqual(user_source.id, charges_copy.id)
        else:
            self.assertEqual(user_source.type, NodeType.TABLE)
            self.assertEqual(user_source.properties["origin"], "cross_dag_view")
        self.assertEqual(set(Node.objects.filter(dag=managed_dag).values_list("id", flat=True)), managed_node_ids)
