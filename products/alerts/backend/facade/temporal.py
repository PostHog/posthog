"""Temporal workflows and activities this product registers on the alerts platform's queues."""

from collections.abc import Callable

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.alerts.backend.temporal.platform_evaluate import (
    PLATFORM_AI_QUEUE_ACTIVITIES,
    PLATFORM_EVALUATION_ACTIVITIES as _EVALUATION_ACTIVITIES,
    PLATFORM_EVALUATION_WORKFLOWS as _EVALUATION_WORKFLOWS,
)
from products.alerts.backend.temporal.platform_late_chart import LATE_CHART_ACTIVITIES, LATE_CHART_WORKFLOWS
from products.alerts.backend.temporal.platform_native_cleanup import NATIVE_CLEANUP_ACTIVITIES, NATIVE_CLEANUP_WORKFLOWS

# The evaluation workflow starts the late chart by name on its own queue, so both run on one worker.
PLATFORM_EVALUATION_WORKFLOWS = [*_EVALUATION_WORKFLOWS, *LATE_CHART_WORKFLOWS, *NATIVE_CLEANUP_WORKFLOWS]
PLATFORM_EVALUATION_ACTIVITIES: list[Callable[..., object]] = [
    *_EVALUATION_ACTIVITIES,
    *LATE_CHART_ACTIVITIES,
    *NATIVE_CLEANUP_ACTIVITIES,
]

__all__ = [
    "PLATFORM_AI_QUEUE_ACTIVITIES",
    "PLATFORM_EVALUATION_ACTIVITIES",
    "PLATFORM_EVALUATION_WORKFLOWS",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(queue_setting="MAX_AI_TASK_QUEUE", activities=tuple(PLATFORM_AI_QUEUE_ACTIVITIES)),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(PLATFORM_EVALUATION_WORKFLOWS),
            activities=tuple(PLATFORM_EVALUATION_ACTIVITIES),
        ),
    ),
)
