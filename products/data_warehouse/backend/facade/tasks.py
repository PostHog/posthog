"""
Celery task wiring for data_warehouse.

Re-export of the beat-scheduled task that core registers (posthog/tasks/scheduled.py).
"""

from products.data_warehouse.backend.tasks import send_external_data_failure_digest_catchup

__all__ = ["send_external_data_failure_digest_catchup"]
