"""The conversations Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.conversations.backend.temporal import (
    ACTIVITIES as CONVERSATIONS_ACTIVITIES,
    WORKFLOWS as CONVERSATIONS_WORKFLOWS,
)
from products.conversations.backend.temporal.channel_summary.schedule import create_channel_summary_coordinator_schedule
from products.conversations.backend.temporal.schedule import create_support_reply_coordinator_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="VIDEO_EXPORT_TASK_QUEUE",
            workflows=tuple(CONVERSATIONS_WORKFLOWS),
            activities=tuple(CONVERSATIONS_ACTIVITIES),
        ),
    ),
    schedules=(create_support_reply_coordinator_schedule, create_channel_summary_coordinator_schedule),
)
