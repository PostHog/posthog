"""Temporal workflows and activities this product registers on the alerts platform's queues."""

from products.alerts.backend.temporal.platform_evaluate import (
    PLATFORM_AI_QUEUE_ACTIVITIES,
    PLATFORM_EVALUATION_ACTIVITIES as _EVALUATION_ACTIVITIES,
    PLATFORM_EVALUATION_WORKFLOWS as _EVALUATION_WORKFLOWS,
)
from products.alerts.backend.temporal.platform_late_chart import LATE_CHART_ACTIVITIES, LATE_CHART_WORKFLOWS

# The evaluation workflow starts the late chart by name on its own queue, so both run on one worker.
PLATFORM_EVALUATION_WORKFLOWS = [*_EVALUATION_WORKFLOWS, *LATE_CHART_WORKFLOWS]
PLATFORM_EVALUATION_ACTIVITIES = [*_EVALUATION_ACTIVITIES, *LATE_CHART_ACTIVITIES]

__all__ = [
    "PLATFORM_AI_QUEUE_ACTIVITIES",
    "PLATFORM_EVALUATION_ACTIVITIES",
    "PLATFORM_EVALUATION_WORKFLOWS",
]
