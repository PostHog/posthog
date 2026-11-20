"""The batch exports declaration that core's worker and scheduler read through ``facade/temporal.py``.

It imports every destination's vendor SDK, so the facade resolves it lazily.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor
from products.batch_exports.backend.temporal.workflows import ACTIVITIES, WORKFLOWS

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="SYNC_BATCH_EXPORTS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
        QueueBinding(
            queue_setting="BATCH_EXPORTS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
    interceptors=(BatchExportsMetricsInterceptor,),
)
