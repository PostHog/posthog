"""Temporal workflows and activities this product registers on the alerts platform's queues."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.alerts.backend.temporal.platform_evaluate import PLATFORM_AI_QUEUE_ACTIVITIES
from products.alerts.backend.temporal.registry import (
    PLATFORM_EVALUATION_ACTIVITIES as _EVALUATION_ACTIVITIES,
    PLATFORM_EVALUATION_WORKFLOWS as _EVALUATION_WORKFLOWS,
)

# The worker's registration test reads the AI queue list from here.
__all__ = ["PLATFORM_AI_QUEUE_ACTIVITIES"]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(queue_setting="MAX_AI_TASK_QUEUE", activities=tuple(PLATFORM_AI_QUEUE_ACTIVITIES)),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(_EVALUATION_WORKFLOWS),
            activities=tuple(_EVALUATION_ACTIVITIES),
        ),
    ),
)
