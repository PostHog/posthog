"""
Temporal registration wiring for batch_exports.

``TEMPORAL`` is the declaration that core's Temporal loaders read by name
(``load_registrations``: the worker, the scheduler and the catalog). It is assigned here, and the
module defines no ``__getattr__``, so a static reader sees what it registers. Building it imports
every destination's vendor SDK (databricks, snowflake, bigquery, ...), so this module may only be
imported where those loaders run, never on the startup path;
``posthog/test/repo_invariants/test_startup_import_budget.py`` holds that.

The worker bootstrap commands (``start_temporal_workflow``, ``execute_temporal_workflow``) take
``WORKFLOWS`` from here.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor as _MetricsInterceptor
from products.batch_exports.backend.temporal.workflows import (
    ACTIVITIES as _ACTIVITIES,
    WORKFLOWS,
)

__all__ = ["WORKFLOWS"]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="SYNC_BATCH_EXPORTS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(_ACTIVITIES)
        ),
        QueueBinding(
            queue_setting="BATCH_EXPORTS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(_ACTIVITIES)
        ),
    ),
    interceptors=(_MetricsInterceptor,),
)
