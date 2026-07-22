"""
Celery task wiring for data_warehouse.

Re-export of the beat-scheduled task that core registers (posthog/tasks/scheduled.py).
"""

from products.data_warehouse.backend.tasks import (
    reconcile_all_managed_warehouse_tables_task,
    send_external_data_failure_digest_catchup,
    sync_team_earliest_event_date,
)
from products.data_warehouse.backend.tasks.tasks import schedule_external_data_failure_digest

__all__ = [
    "reconcile_all_managed_warehouse_tables_task",
    "schedule_external_data_failure_digest",
    "send_external_data_failure_digest_catchup",
    "sync_team_earliest_event_date",
]
