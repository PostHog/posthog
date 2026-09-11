"""Facade re-export for the customer_analytics Celery tasks that core schedules.

Core's beat schedule (``posthog/tasks/scheduled.py``) imports the task object and calls ``.s()``
on it, so the wiring crosses the boundary as an object, not data. Each ``name=`` is pinned in
``tasks/tasks.py``, so the registered task identity is independent of the import path.
"""

from products.customer_analytics.backend.tasks.tasks import reconcile_ownership_claims_task

__all__ = ["reconcile_ownership_claims_task"]
