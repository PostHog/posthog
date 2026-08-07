"""
Backfill-status wiring for data_warehouse.

The managed-warehouse backfill jobs run in core's Dagster code location, so the scheduler-agnostic
status recording API (logic.backfill_status) crosses the product boundary through this facade.
"""

from products.data_warehouse.backend.logic.backfill_status import (
    BackfillOutcome,
    get_months_in_range,
    historical_backfill_months,
    record_backfill_finished,
    record_backfill_outcome,
    record_backfill_started,
    stale_running_partitions,
)

__all__ = [
    "BackfillOutcome",
    "get_months_in_range",
    "historical_backfill_months",
    "record_backfill_finished",
    "record_backfill_outcome",
    "record_backfill_started",
    "stale_running_partitions",
]
