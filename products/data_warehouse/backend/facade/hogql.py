"""
HogQL-adjacent wiring for data_warehouse.

Light re-export of the sync-warning helper the HogQL database builder surfaces on
warehouse tables. Kept out of the heavy ``facade.api`` so the HogQL/setup path does
not pull the data-load/s3 machinery.
"""

from products.data_warehouse.backend.sync_status import get_warehouse_sync_warnings

__all__ = ["get_warehouse_sync_warnings"]
