"""Temporal wiring re-exports — the only path core may use to register this
product's workflows, activities, and schedule."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from ..temporal import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)
from ..temporal.schedule import create_autoresearch_daily_schedule as create_autoresearch_daily_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(queue_setting="AUTORESEARCH_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),
    ),
    schedules=(create_autoresearch_daily_schedule,),
)
