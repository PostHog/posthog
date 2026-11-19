"""Temporal workflows and activities the canvas build worker registers."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.canvas.backend.temporal.registry import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)

TEMPORAL = TemporalRegistration(
    queues=(
        # Canvas builds. CANVAS_BUILD_TASK_QUEUE defaults to the general-purpose queue name (so it merges
        # into that fleet until a dedicated worker exists).
        QueueBinding(queue_setting="CANVAS_BUILD_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),
    ),
)
