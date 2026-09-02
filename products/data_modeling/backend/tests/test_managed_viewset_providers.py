from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import IntegerDatabaseField

from products.data_modeling.backend.facade.managed_viewset_hooks import (
    ProvidedView,
    _expected_views_providers,
    register_expected_views_provider,
)
from products.data_modeling.backend.facade.models import (
    DAG,
    REVENUE_ANALYTICS_DAG_NAME,
    DataWarehouseManagedViewSet,
    DataWarehouseSavedQuery,
)
from products.data_modeling.backend.logic.cohort_scheduling import is_tier_schedule_id
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

SCHEDULE_MATERIALIZATION = (
    "products.data_modeling.backend.models.datawarehouse_saved_query.DataWarehouseSavedQuery.schedule_materialization"
)
# A vehicle kind for these tests — the CharField needs a real enum member, but the tests are
# about the provider mechanism, not about anything specific to engineering analytics.
KIND = DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS

SERVICE = "products.data_warehouse.backend.logic.data_load.saved_query_service"
GET_V2_DAG_IDS = "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids"
RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"
NODE_MAT = "products.data_modeling.backend.logic.node_materialization"
SYNC_SAVED_QUERY_TO_DAG = "products.data_modeling.backend.logic.saved_query_dag_sync.sync_saved_query_to_dag"


def _no_schedules():
    """A Temporal client whose schedule listing is empty — a DAG nothing has ever scheduled."""

    async def list_schedules(*_args, **_kwargs):
        async def gen():
            return
            yield  # pragma: no cover - makes gen an async generator

        return gen()

    temporal = Mock()
    temporal.list_schedules = list_schedules
    return temporal


def _fake_view(name: str = "fake_provider_view", materialized: bool = True) -> ProvidedView:
    return ProvidedView(
        name=name,
        query="SELECT 1 AS id",
        fields={"id": IntegerDatabaseField(name="id")},
        materialized=materialized,
    )


class TestManagedViewSetProviders(BaseTest):
    def _viewset(self) -> DataWarehouseManagedViewSet:
        return DataWarehouseManagedViewSet.objects.create(team=self.team, kind=KIND)

    def _views(self, viewset: DataWarehouseManagedViewSet) -> list[DataWarehouseSavedQuery]:
        return list(
            DataWarehouseSavedQuery.objects.filter(team=self.team, managed_viewset=viewset).exclude(deleted=True)
        )

    @patch(SCHEDULE_MATERIALIZATION)
    def test_sync_views_creates_non_materialized_view(self, mock_schedule):
        fake_view = _fake_view(materialized=False)
        with patch.dict(_expected_views_providers, clear=True):
            register_expected_views_provider(KIND, lambda team: [fake_view])

            viewset = self._viewset()
            viewset.sync_views()

        views = self._views(viewset)
        view = next(v for v in views if v.name == fake_view.name)
        self.assertFalse(view.is_materialized)
        self.assertIsNone(view.sync_frequency_interval)
        # A non-materialized view is computed at query time — it must never be scheduled for
        # materialization, nor get a managed (revenue-analytics) DAG.
        mock_schedule.assert_not_called()
        self.assertFalse(DAG.objects.filter(team=self.team, name=REVENUE_ANALYTICS_DAG_NAME).exists())

    @patch(SCHEDULE_MATERIALIZATION)
    @patch(SYNC_SAVED_QUERY_TO_DAG)
    @patch("posthog.hogql.database.database.Database.create_for", wraps=Database.create_for)
    def test_sync_views_reuses_database_for_dag_dependencies(
        self, mock_database_create, mock_sync_saved_query_to_dag, _mock_schedule
    ):
        views = [_fake_view(name=f"provided_view_{index}") for index in range(3)]
        with patch.dict(_expected_views_providers, clear=True):
            register_expected_views_provider(KIND, lambda team: views)

            viewset = self._viewset()
            viewset.sync_views()

        self.assertEqual(mock_database_create.call_count, 2)
        self.assertEqual(mock_sync_saved_query_to_dag.call_count, len(views))
        dag_databases = [call.kwargs["database"] for call in mock_sync_saved_query_to_dag.call_args_list]
        self.assertTrue(all(database is dag_databases[0] for database in dag_databases))

    @patch(SCHEDULE_MATERIALIZATION)
    def test_sync_views_is_idempotent(self, _):
        fake_view = _fake_view()
        with patch.dict(_expected_views_providers, clear=True):
            register_expected_views_provider(KIND, lambda team: [fake_view])

            viewset = self._viewset()
            viewset.sync_views()
            first_ids = sorted(v.id for v in self._views(viewset))
            viewset.sync_views()
            second_ids = sorted(v.id for v in self._views(viewset))

        self.assertEqual(first_ids, second_ids)

    def test_provisioning_a_new_team_never_mints_v1_schedules(self):
        # Managed viewsets are how most new teams first materialize anything (a provider makes
        # several views at once), and their DAG is brand new — so without a birth-on-v2 path every
        # view here gets its own v1 per-query schedule. Views after the first must follow the
        # bootstrap too, even though its tier schedules are only created after commit.
        views = [_fake_view(name=f"provided_view_{i}") for i in range(3)]
        with (
            patch.dict(_expected_views_providers, clear=True),
            patch(GET_V2_DAG_IDS, return_value=set()),
            patch(f"{SERVICE}.sync_saved_query_workflow") as sync_wf,
            patch(f"{SERVICE}.saved_query_workflow_exists", return_value=False),
            patch(f"{RECONCILE}.schedule_exists", return_value=False),
            patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            patch(f"{RECONCILE}.sync_connect"),
            patch(f"{RECONCILE}.async_connect", new=AsyncMock(return_value=_no_schedules())),
            patch(f"{RECONCILE}.a_create_schedule", new=AsyncMock()) as create,
            patch(f"{NODE_MAT}.sync_connect"),
        ):
            register_expected_views_provider(KIND, lambda team: views)
            viewset = self._viewset()
            with self.captureOnCommitCallbacks(execute=True):
                viewset.sync_views()

        sync_wf.assert_not_called()
        assert create.call_count > 0
        assert all(is_tier_schedule_id(call.kwargs["id"]) for call in create.call_args_list)
        assert [v.sync_frequency_interval for v in self._views(viewset)] == [None, None, None]

    def test_sync_views_creates_nothing_for_empty_provider(self):
        with patch.dict(_expected_views_providers, clear=True):
            register_expected_views_provider(KIND, lambda team: [])

            viewset = self._viewset()
            viewset.sync_views()

        self.assertEqual(self._views(viewset), [])

    def test_sync_views_raises_for_unregistered_kind(self):
        with patch.dict(_expected_views_providers, clear=True):
            viewset = self._viewset()
            with self.assertRaises(DataWarehouseManagedViewSet.UnsupportedViewsetKind):
                viewset.sync_views()
