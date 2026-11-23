from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.aeo.backend.temporal.brand_sentiment import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]

TEMPORAL = TemporalRegistration(
    queues=(QueueBinding(queue_setting="AEO_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),),
)
