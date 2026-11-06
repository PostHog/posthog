"""
Celery task wiring for data_warehouse.

Re-exports the beat-scheduled task that core registers (posthog/tasks/scheduled.py) and the
managed-warehouse soft-delete and ensure tasks that managed_warehouse tests drive directly.
"""

from products.data_warehouse.backend.tasks import (
    reconcile_all_managed_warehouse_tables_task,
    send_external_data_failure_digest_catchup,
    sync_team_earliest_event_date,
)
from products.data_warehouse.backend.tasks.tasks import (
    ensure_managed_warehouse_direct_source_v2_task,
    schedule_external_data_failure_digest,
    soft_delete_managed_warehouse_sources_task,
    soft_delete_managed_warehouse_sources_v2_task,
)

__all__ = [
    "ensure_managed_warehouse_direct_source_v2_task",
    "reconcile_all_managed_warehouse_tables_task",
    "schedule_external_data_failure_digest",
    "send_external_data_failure_digest_catchup",
    "soft_delete_managed_warehouse_sources_task",
    "soft_delete_managed_warehouse_sources_v2_task",
    "sync_team_earliest_event_date",
]
