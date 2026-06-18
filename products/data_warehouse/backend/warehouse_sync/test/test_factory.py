from posthog.test.base import BaseTest

from django.test import override_settings

from products.data_warehouse.backend.warehouse_sync.dagster_provider import DagsterBackfillStatusProvider
from products.data_warehouse.backend.warehouse_sync.factory import get_warehouse_sync_status_provider
from products.data_warehouse.backend.warehouse_sync.viaduck_provider import ViaduckSyncStatusProvider


class TestFactory(BaseTest):
    @override_settings(WAREHOUSE_SYNC_BACKEND="dagster")
    def test_defaults_to_dagster(self) -> None:
        assert isinstance(get_warehouse_sync_status_provider("org-1"), DagsterBackfillStatusProvider)

    @override_settings(WAREHOUSE_SYNC_BACKEND="viaduck")
    def test_selects_viaduck(self) -> None:
        assert isinstance(get_warehouse_sync_status_provider("org-1"), ViaduckSyncStatusProvider)
