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
