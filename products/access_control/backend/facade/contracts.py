"""
Contract types for access_control.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django/DRF imports here.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
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


@dataclass(frozen=True)
class SetObjectAccessControlInput:
    """Input for granting, changing, or removing one subject's access to one object.

    `access_level=None` removes the rule. Exactly one of `organization_member_id` or `role_id`
    names the subject.
    """

    resource: str
    resource_id: str
    access_level: str | None
    organization_member_id: UUID | None = None
    role_id: UUID | None = None
    created_by_id: int | None = None

    def __post_init__(self) -> None:
        if (self.organization_member_id is None) == (self.role_id is None):
            raise ValueError("Set exactly one of organization_member_id or role_id.")


@dataclass(frozen=True)
class ObjectAccessControlRule:
    """One object-level access control rule as stored."""

    id: UUID
    resource: str
    resource_id: str
    access_level: str
    organization_member_id: UUID | None
    role_id: UUID | None
