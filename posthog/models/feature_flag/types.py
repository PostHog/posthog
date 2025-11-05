"""Type definitions for feature flag data structures."""

from enum import StrEnum
from typing import Any, TypedDict


class PropertyFilterType(StrEnum):
    """Enum for property filter types used in feature flag filtering."""

    FLAG = "flag"
    COHORT = "cohort"
    PERSON = "person"
    GROUP = "group"


class FlagProperty(TypedDict, total=False):
    """Property within a feature flag filter group."""

    key: str
    type: str
    value: Any
    operator: str
    dependency_chain: list[str]  # Optional: only present for flag dependencies


class FilterGroup(TypedDict):
    """Filter group within a feature flag."""

    properties: list[FlagProperty]
    rollout_percentage: float


class FlagFilters(TypedDict):
    """Filter configuration for a feature flag."""

    groups: list[FilterGroup]


class FlagData(TypedDict):
    """Complete feature flag data structure."""

    key: str
    filters: FlagFilters


class FlagResponse(TypedDict):
    """Response structure for local evaluation endpoint."""

    flags: list[FlagData]
    group_type_mapping: dict[str, str]
    cohorts: dict[str, dict[str, Any]]
