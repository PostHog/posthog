"""
Shared types for messaging workflows.
"""

import dataclasses
from typing import Any


@dataclasses.dataclass
class PersonPropertyFilter:
    """Person property filter to evaluate."""

    condition_hash: str
    bytecode: list[Any]  # HogQL bytecode
    cohort_ids: list[int]  # Cohorts that use this condition
    property_key: str | None  # The person property key (e.g., 'email', '$host')


@dataclasses.dataclass
class BehavioralEventFilter:
    """Behavioral event filter for backfilling precalculated events."""

    condition_hash: str
    bytecode: list[Any]  # HogQL bytecode
    cohort_ids: list[int]  # Cohorts that use this condition
    event_name: str  # Target event name (e.g., '$pageview')
    time_value: int  # Lookback window size (e.g., 30)
    time_interval: str  # Lookback window unit (e.g., 'day', 'week', 'month')
    event_filters: list[dict] | None = None  # Optional per-event property sub-filters
