"""Facade re-exports for Temporal wiring.

The worker bootstrap (`start_temporal_worker`) and the schedule bootstrap register the catalog's
digest through these re-exports rather than importing ``backend.temporal`` directly.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from ..temporal import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)
from ..temporal.schedule import (
    create_data_catalog_effectiveness_schedule as create_data_catalog_effectiveness_schedule,
    create_data_catalog_usage_scan_schedule as create_data_catalog_usage_scan_schedule,
    create_data_catalog_weekly_digest_schedule as create_data_catalog_weekly_digest_schedule,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="WEEKLY_DIGEST_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
    schedules=(
        create_data_catalog_weekly_digest_schedule,
        create_data_catalog_usage_scan_schedule,
        create_data_catalog_effectiveness_schedule,
    ),
)
