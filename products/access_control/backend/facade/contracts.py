"""
Contract types for access_control.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django/DRF imports here.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID


class PropertyAccessLevel(str, Enum):
    """Effective access level for a property."""

    READ_WRITE = "read_write"
    READ = "read"
    NONE = "none"

    def grants_access(self) -> bool:
        """Returns True if this level allows the property to be read in queries."""
        return self in (PropertyAccessLevel.READ_WRITE, PropertyAccessLevel.READ)


# --- Output DTOs ---


@dataclass(frozen=True)
class PropertyAccessControlRule:
    """A single access control rule for a property definition."""

    id: UUID
    property_definition_id: UUID
    access_level: PropertyAccessLevel
    organization_member_id: UUID | None
    role_id: UUID | None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PropertyAccessControlState:
    """The full access control state for a property definition."""

    rules: list[PropertyAccessControlRule] = field(default_factory=list)
    available_access_levels: list[PropertyAccessLevel] = field(default_factory=list)
    default_access_level: PropertyAccessLevel = PropertyAccessLevel.READ_WRITE


# --- Input DTOs ---


@dataclass(frozen=True)
class UpsertPropertyAccessControlInput:
    """Input for creating or updating an access control rule."""

    property_definition_id: str
    access_level: PropertyAccessLevel
    organization_member_id: UUID | None = None
    role_id: UUID | None = None


@dataclass(frozen=True)
class DeletePropertyAccessControlInput:
    """Input for deleting an access control rule."""

    property_definition_id: str
    organization_member_id: UUID | None = None
    role_id: UUID | None = None


# --- Access decisions ---

# The verbs callers ask about. Each maps to a rung on the resource's access-level ladder
# (see facade/access.py); new verbs need a rung before they can be checked.
Action = Literal["view", "edit", "manage", "create", "list"]

AccessSource = Literal[
    "object",
    "parent_object",
    "resource",
    "parent_resource",
    "system_default",
    "org_admin",
    "creator",
    "org_membership",
]


@dataclass(frozen=True)
class AccessDecision:
    """Why a principal can or cannot perform an action: the resolved level and the rule that supplied it."""

    allowed: bool
    action: Action
    resource: str
    object_id: str | None
    level: str | None
    required_level: str | None
    source: AccessSource | None
    source_subject: Literal["member", "role", "default"] | None
