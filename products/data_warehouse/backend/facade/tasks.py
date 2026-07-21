"""
Celery task wiring for data_warehouse.

Re-export of the beat-scheduled task that core registers (posthog/tasks/scheduled.py).
"""

from products.data_warehouse.backend.tasks import (
    reconcile_all_managed_warehouse_tables_task,
    send_external_data_failure_digest_catchup,
)

__all__ = ["reconcile_all_managed_warehouse_tables_task", "send_external_data_failure_digest_catchup"]
