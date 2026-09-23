"""Metric emitters for the shared alerts platform, as a source adapter sees them.

A source evaluates its own data but runs on the platform's schedule and writes the platform's
rows, so what a check cost and what it decided are the platform's numbers to name. Kept apart
from `facade/temporal.py`, which pulls in the workflow module.
"""

from products.alerts.backend.temporal.metrics import (
    increment_checks,
    increment_deliveries_deferred,
    increment_state_transition,
    record_batch_duration,
    record_scheduler_lag,
    safe_record,
)

__all__ = [
    "increment_checks",
    "increment_deliveries_deferred",
    "increment_state_transition",
    "record_batch_duration",
    "record_scheduler_lag",
    "safe_record",
]
