"""Temporal workflows and activities this product registers on the alerts platform's queues."""

from products.alerts.backend.temporal.platform_evaluate import (
    PLATFORM_AI_QUEUE_ACTIVITIES,
    PLATFORM_EVALUATION_ACTIVITIES,
    PLATFORM_EVALUATION_WORKFLOWS,
)

__all__ = [
    "PLATFORM_AI_QUEUE_ACTIVITIES",
    "PLATFORM_EVALUATION_ACTIVITIES",
    "PLATFORM_EVALUATION_WORKFLOWS",
]
