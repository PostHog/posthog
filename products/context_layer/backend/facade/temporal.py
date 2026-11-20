"""The context layer Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.context_layer.backend.temporal import (
    ACTIVITIES as CONTEXT_LAYER_ACTIVITIES,
    WORKFLOWS as CONTEXT_LAYER_WORKFLOWS,
)
from products.context_layer.backend.temporal.schedule import create_context_layer_dream_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE",
            workflows=tuple(CONTEXT_LAYER_WORKFLOWS),
            activities=tuple(CONTEXT_LAYER_ACTIVITIES),
        ),
    ),
    schedules=(create_context_layer_dream_schedule,),
)
