"""
Celery task wiring for data_warehouse.

Re-export of the beat-scheduled task that core registers (posthog/tasks/scheduled.py).
"""

from products.data_warehouse.backend.tasks import send_external_data_failure_digest_catchup
from products.data_warehouse.backend.tasks.tasks import schedule_external_data_failure_digest

__all__ = ["schedule_external_data_failure_digest", "send_external_data_failure_digest_catchup"]
