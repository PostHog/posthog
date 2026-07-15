from posthog.test.base import BaseTest
from unittest.mock import patch

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
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

SCHEDULE_MATERIALIZATION = (
    "products.data_modeling.backend.models.datawarehouse_saved_query.DataWarehouseSavedQuery.schedule_materialization"
)
# A vehicle kind for these tests — the CharField needs a real enum member, but the tests are
# about the provider mechanism, not about anything specific to engineering analytics.
KIND = DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS


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
