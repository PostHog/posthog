"""The billing alerts Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.billing_alerts.backend.temporal import (
    ACTIVITIES as BILLING_ALERTS_ACTIVITIES,
    PLATFORM_EVALUATION_ACTIVITIES as BILLING_PLATFORM_EVALUATION_ACTIVITIES,
    PLATFORM_EVALUATION_WORKFLOWS as BILLING_PLATFORM_EVALUATION_WORKFLOWS,
    WORKFLOWS as BILLING_ALERTS_WORKFLOWS,
)
from products.billing_alerts.backend.temporal.schedule import create_schedule_due_billing_alert_checks_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="BILLING_TASK_QUEUE",
            workflows=tuple(BILLING_ALERTS_WORKFLOWS),
            activities=tuple(BILLING_ALERTS_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(BILLING_PLATFORM_EVALUATION_WORKFLOWS),
            activities=tuple(BILLING_PLATFORM_EVALUATION_ACTIVITIES),
        ),
    ),
    schedules=(create_schedule_due_billing_alert_checks_schedule,),
)
