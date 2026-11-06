"""Facade re-exports for Temporal wiring.

The worker bootstrap (`start_temporal_worker`) and the schedule bootstrap register the catalog's
digest through these re-exports rather than importing ``backend.temporal`` directly.
"""

from ..temporal import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)
from ..temporal.schedule import create_data_catalog_weekly_digest_schedule as create_data_catalog_weekly_digest_schedule
