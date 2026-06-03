from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules import Command
from products.data_modeling.backend.models import DAG, DEFAULT_DAG_NAME, REVENUE_ANALYTICS_DAG_NAME, Node
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.services.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind

COMMAND_PATH = "products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules"


@pytest.mark.django_db
class TestMigrateTeamsToDagSchedules(BaseTest):
    def setUp(self):
        super().setUp()
        self.schedule_exists_patch = mock.patch(f"{COMMAND_PATH}.schedule_exists", return_value=False)
        self.create_schedule_patch = mock.patch(f"{COMMAND_PATH}.create_schedule")
        self.delete_schedule_patch = mock.patch(f"{COMMAND_PATH}.delete_schedule")
        self.sync_connect_patch = mock.patch(f"{COMMAND_PATH}.sync_connect", return_value=mock.MagicMock())
        self.mock_schedule_exists = self.schedule_exists_patch.start()
        self.mock_create_schedule = self.create_schedule_patch.start()
        self.mock_delete_schedule = self.delete_schedule_patch.start()
        self.sync_connect_patch.start()
        self.addCleanup(self.schedule_exists_patch.stop)
        self.addCleanup(self.create_schedule_patch.stop)
        self.addCleanup(self.delete_schedule_patch.stop)
        self.addCleanup(self.sync_connect_patch.stop)

    def _create_model(self, name: str, interval: timedelta = timedelta(hours=24)) -> DataWarehouseSavedQuery:
        sq = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=interval,
            is_materialized=True,
        )
        sync_saved_query_to_dag(sq)  # creates a node in the Default DAG
        return sq

    def _create_managed_view(
        self, name: str, query: str = "SELECT 1", interval: timedelta = timedelta(hours=12)
    ) -> DataWarehouseSavedQuery:
        mv, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        sq = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": query, "kind": "HogQLQuery"},
            managed_viewset=mv,
            sync_frequency_interval=interval,
            is_materialized=True,
            origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
        )
        return sq

    def _run(self):
        call_command("migrate_teams_to_dag_schedules", team_ids=str(self.team.id))

    def _schedule_calls_by_id(self) -> dict:
        return {c.kwargs["id"]: c.kwargs["search_attributes"] for c in self.mock_create_schedule.call_args_list}

    def test_managed_views_get_dedicated_protected_dag_and_tagged_schedule(self):
        sq1 = self._create_managed_view("revenue_view_1")
        sq2 = self._create_managed_view("revenue_view_2")
        # simulate the 0006 backfill having placed them in the Default DAG
        sync_saved_query_to_dag(sq1)
        sync_saved_query_to_dag(sq2)

        self._run()

        ra_dag = DAG.objects.get(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME)
        # both views moved into the RA DAG and out of every other DAG
        for sq in (sq1, sq2):
            assert Node.objects.filter(dag=ra_dag, saved_query=sq).exists()
            assert not Node.objects.filter(saved_query=sq).exclude(dag=ra_dag).exists()

        calls = self._schedule_calls_by_id()
        assert str(ra_dag.id) in calls
        assert calls[str(ra_dag.id)].get(POSTHOG_SCHEDULE_TYPE_KEY) == "revenue_analytics"

        # old v1 schedules deleted and intervals nulled so v1 isn't re-created
        deleted_ids = {c.kwargs["schedule_id"] for c in self.mock_delete_schedule.call_args_list}
        assert {str(sq1.id), str(sq2.id)} <= deleted_ids
        sq1.refresh_from_db()
        sq2.refresh_from_db()
        assert sq1.sync_frequency_interval is None
        assert sq2.sync_frequency_interval is None

    def test_non_managed_models_stay_on_default_dag(self):
        sq = self._create_model("plain_model")

        self._run()

        default_dag = DAG.objects.get(team=self.team, name=DEFAULT_DAG_NAME)
        assert not DAG.objects.filter(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME).exists()

        calls = self._schedule_calls_by_id()
        assert str(default_dag.id) in calls
        # the Default schedule is not tagged as revenue analytics
        assert calls[str(default_dag.id)].get(POSTHOG_SCHEDULE_TYPE_KEY) is None
        sq.refresh_from_db()
        assert sq.sync_frequency_interval is None

    def test_mixed_team_splits_into_two_schedules(self):
        plain = self._create_model("plain_model")
        managed = self._create_managed_view("revenue_view")
        sync_saved_query_to_dag(managed)  # backfilled into Default

        self._run()

        default_dag = DAG.objects.get(team=self.team, name=DEFAULT_DAG_NAME)
        ra_dag = DAG.objects.get(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME)

        calls = self._schedule_calls_by_id()
        assert calls[str(default_dag.id)].get(POSTHOG_SCHEDULE_TYPE_KEY) is None
        assert calls[str(ra_dag.id)].get(POSTHOG_SCHEDULE_TYPE_KEY) == "revenue_analytics"

        assert Node.objects.filter(dag=default_dag, saved_query=plain).exists()
        assert Node.objects.filter(dag=ra_dag, saved_query=managed).exists()
        assert not Node.objects.filter(dag=default_dag, saved_query=managed).exists()

    def test_managed_only_team_creates_no_default_schedule(self):
        self._create_managed_view("revenue_view_1")
        self._create_managed_view("revenue_view_2")

        self._run()

        ra_dag = DAG.objects.get(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME)
        calls = self._schedule_calls_by_id()
        assert list(calls.keys()) == [str(ra_dag.id)]

    def test_idempotent_when_schedule_already_exists(self):
        self._create_managed_view("revenue_view")
        self.mock_schedule_exists.return_value = True

        self._run()

        self.mock_create_schedule.assert_not_called()

    def test_sync_nodes_multi_pass_handles_dependency_order(self):
        # view_a can only resolve after view_b is in the DAG; passing a-first forces a retry
        view_a = self._create_managed_view("view_a")
        view_b = self._create_managed_view("view_b")
        ra_dag = DAG.get_or_create_revenue_analytics(self.team)
        synced: list = []

        def fake_sync(sq, dag=None):
            if sq.id == view_a.id and view_b.id not in synced:
                raise Exception("dependency not ready")
            synced.append(sq.id)

        with mock.patch(f"{COMMAND_PATH}.sync_saved_query_to_dag", side_effect=fake_sync):
            Command()._sync_nodes_into_dag([view_a, view_b], ra_dag, self.team)

        assert synced == [view_b.id, view_a.id]
