"""The business knowledge Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.business_knowledge.backend.temporal import (
    ACTIVITIES as BUSINESS_KNOWLEDGE_ACTIVITIES,
    WORKFLOWS as BUSINESS_KNOWLEDGE_WORKFLOWS,
)
from products.business_knowledge.backend.temporal.schedule import (
    create_business_knowledge_learning_coordinator_schedule,
    create_business_knowledge_refresh_coordinator_schedule,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="VIDEO_EXPORT_TASK_QUEUE",
            workflows=tuple(BUSINESS_KNOWLEDGE_WORKFLOWS),
            activities=tuple(BUSINESS_KNOWLEDGE_ACTIVITIES),
        ),
    ),
    schedules=(
        create_business_knowledge_learning_coordinator_schedule,
        create_business_knowledge_refresh_coordinator_schedule,
    ),
)
