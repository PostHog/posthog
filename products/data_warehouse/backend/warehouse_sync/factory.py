from django.conf import settings

from products.data_warehouse.backend.warehouse_sync.base import WarehouseSyncStatusProvider
from products.data_warehouse.backend.warehouse_sync.dagster_provider import DagsterBackfillStatusProvider
from products.data_warehouse.backend.warehouse_sync.viaduck_provider import ViaduckSyncStatusProvider


def get_warehouse_sync_status_provider(organization_id: str) -> WarehouseSyncStatusProvider:
    backend = getattr(settings, "WAREHOUSE_SYNC_BACKEND", "dagster")
    if backend == "viaduck":
        return ViaduckSyncStatusProvider()
    return DagsterBackfillStatusProvider()
