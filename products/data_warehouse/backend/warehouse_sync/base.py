from typing import Protocol

from products.data_warehouse.backend.warehouse_sync.contracts import WarehouseSyncStatusDTO


class WarehouseSyncStatusProvider(Protocol):
    backend: str

    def get_status(self, organization_id: str) -> WarehouseSyncStatusDTO: ...
