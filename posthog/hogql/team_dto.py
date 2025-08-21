"""Team Data Transfer Objects for HogQL.

This module defines protobuf-like data structures for Team objects
used within the HogQL subsystem to decouple from Django ORM dependencies.
"""

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID


@dataclass(frozen=True)
class TeamDTO:
    """Immutable Team data transfer object containing all fields accessed by HogQL code.

    This DTO contains only the Team model fields that are actually used
    within the hogql package, providing a clean interface that decouples
    HogQL from the Django ORM Team model.
    """

    # Core identifier fields
    id: int
    uuid: UUID
    project_id: int

    # Configuration fields
    timezone: str
    week_start_day: Optional[int]
    modifiers: Optional[dict[str, Any]]
    test_account_filters: list[dict[str, Any]]
    path_cleaning_filters: Optional[list[dict[str, Any]]]

    # Relationship fields - minimal data needed
    organization_id: UUID

    # Computed/derived fields that HogQL needs
    person_on_events_mode_flag_based_default: str
    person_on_events_mode: str
    default_modifiers: dict[str, Any]

    # Timezone info (as string representation for serialization)
    timezone_info: str

    # Path cleaning filter models (as serialized data)
    path_cleaning_filter_models_data: list[dict[str, Any]]
