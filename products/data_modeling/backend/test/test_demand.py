from datetime import datetime, timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models import Team

from products.data_modeling.backend.logic.demand import record_saved_query_demand
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType


class TestRecordSavedQueryDemand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = self._view("base_view", "select event from events")
        self.child = self._view("child_view", "select event from base_view")
        self.sibling = self._view("sibling_view", "select event from events")

    def _view(self, name: str, query: str) -> DataWarehouseSavedQuery:
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": query}
        )
        sync_saved_query_to_dag(view, reconcile=False)
        return view

    def _stamps(self) -> dict[str, datetime | None]:
        return {
            str(node.saved_query_id): node.last_demand_at
            for node in Node.objects.filter(team=self.team, saved_query__isnull=False)
        }

    def test_demand_reaches_ancestors_and_stays_within_the_team(self) -> None:
        read_at = timezone.now().replace(microsecond=0)
        other_team = Team.objects.create(organization=self.organization)

        assert record_saved_query_demand(other_team.pk, {str(self.child.id): read_at}) == 0
        assert all(stamp is None for stamp in self._stamps().values())

        reached = record_saved_query_demand(self.team.pk, {str(self.child.id): read_at})
        assert reached == Node.objects.filter(team=self.team, last_demand_at=read_at).count()
        stamps = self._stamps()
        assert stamps[str(self.child.id)] == read_at
        assert stamps[str(self.base.id)] == read_at
        assert stamps[str(self.sibling.id)] is None

    def test_demand_never_moves_backwards(self) -> None:
        now = timezone.now().replace(microsecond=0)
        record_saved_query_demand(self.team.pk, {str(self.child.id): now})
        record_saved_query_demand(self.team.pk, {str(self.child.id): now - timedelta(hours=1)})
        assert self._stamps()[str(self.base.id)] == now

        record_saved_query_demand(self.team.pk, {str(self.base.id): now + timedelta(hours=1)})
        stamps = self._stamps()
        assert stamps[str(self.base.id)] == now + timedelta(hours=1)
        assert stamps[str(self.child.id)] == now

    def test_demand_crosses_a_reference_into_the_dag_that_owns_the_model(self) -> None:
        read_at = timezone.now().replace(microsecond=0)
        managed_dag = DAG.objects.create(team=self.team, name="Managed DAG")
        managed_node = Node.objects.create(
            team=self.team, dag=managed_dag, saved_query=self.sibling, type=NodeType.VIEW
        )
        managed_source = Node.objects.create(team=self.team, dag=managed_dag, name="events", type=NodeType.TABLE)
        Edge.objects.create(team=self.team, dag=managed_dag, source=managed_source, target=managed_node)

        default_dag = Node.objects.get(team=self.team, saved_query=self.child).dag
        reference = Node.objects.create(
            team=self.team,
            dag=default_dag,
            name="managed_reference",
            type=NodeType.TABLE,
            properties={"origin": "cross_dag_view", "saved_query_id": str(self.sibling.id)},
        )
        consumer = self._view("consumer_view", "select 1 as event")
        consumer_node = Node.objects.get(team=self.team, dag=default_dag, saved_query=consumer)
        Edge.objects.create(team=self.team, dag=default_dag, source=reference, target=consumer_node)

        record_saved_query_demand(self.team.pk, {str(consumer.id): read_at})

        for node in [consumer_node, reference, managed_node, managed_source]:
            node.refresh_from_db()
            assert node.last_demand_at == read_at, node.name
        assert self._stamps()[str(self.child.id)] is None
