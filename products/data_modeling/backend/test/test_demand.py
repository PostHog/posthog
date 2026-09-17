from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models import Team

from products.data_modeling.backend.logic.demand import record_saved_query_demand
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node


class TestRecordSavedQueryDemand(BaseTest):
    def setUp(self):
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

    def _stamps(self) -> dict:
        return {
            str(node.saved_query_id): node.last_demand_at
            for node in Node.objects.filter(team=self.team, saved_query__isnull=False)
        }

    def test_demand_reaches_ancestors_and_stays_within_the_team(self):
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

    def test_demand_never_moves_backwards(self):
        now = timezone.now().replace(microsecond=0)
        record_saved_query_demand(self.team.pk, {str(self.child.id): now})
        record_saved_query_demand(self.team.pk, {str(self.child.id): now - timedelta(hours=1)})
        assert self._stamps()[str(self.base.id)] == now

        record_saved_query_demand(self.team.pk, {str(self.base.id): now + timedelta(hours=1)})
        stamps = self._stamps()
        assert stamps[str(self.base.id)] == now + timedelta(hours=1)
        assert stamps[str(self.child.id)] == now
