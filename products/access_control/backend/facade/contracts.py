"""
Contract types for access_control.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django/DRF imports here.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject


class PropertyAccessLevel(str, Enum):
    """Effective access level for a property."""

    READ_WRITE = "read_write"
    READ = "read"
    NONE = "none"

    def grants_access(self) -> bool:
        """Returns True if this level allows the property to be read in queries."""
        return self in (PropertyAccessLevel.READ_WRITE, PropertyAccessLevel.READ)


class UserNotOrganizationMemberError(ValueError):
    """The user has no membership in the organization, so their property access cannot be resolved."""


# --- Output DTOs ---


@dataclass(frozen=True)
class RestrictedPropertyNames:
    """Restricted property names grouped by event, person, and group scope."""

    event: frozenset[str]
    person: frozenset[str]
    # Keyed by group type index. Names under None are restricted for every group type.
    group: dict[int | None, frozenset[str]] = field(default_factory=dict)

    def is_group_property_restricted(self, name: str, group_type_index: int | None) -> bool:
        """With no group type index, a name restricted for any group type counts as restricted."""
        return name in self.group_property_names(group_type_index)

    def group_property_names(self, group_type_index: int | None) -> frozenset[str]:
        """Restricted names for one group type. With no group type index, names restricted for any group type."""
        if group_type_index is None:
            return frozenset().union(*self.group.values())
        return self.group.get(None, frozenset()) | self.group.get(group_type_index, frozenset())


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


@frozen
class PropertyDefinitionLabel:
    """How a property access control rule names its property definition."""

    id: UUID
    name: str
    is_person: bool


# --- Input DTOs ---


@frozen
class FallbackParent:
    """The parent a reference falls back to. `resource` must match `RESOURCE_FALLBACK_MAP`; `id=None` means no parent."""

    resource: APIScopeObject
    id: str | None


@frozen
class ObjectAccessRef:
    """The fields object-level access control reads from one object, without the model.

    A view that serves a facade contract returns this from `object_access_ref()` in place of a
    model instance. Resolution needs the resource, the object id, and the creator. A resource that
    inherits access from a parent object through a foreign key (`RESOURCE_FALLBACK_MAP`) also needs
    `fallback_parent`, read off that foreign key. Without it the check raises, because resolution
    would skip the parent's rules.
    """

    resource: APIScopeObject
    id: str
    team_id: int
    created_by_id: int | None
    fallback_parent: FallbackParent | None = None


@frozen
class UpsertPropertyAccessControlInput:
    """Input for creating or updating an access control rule."""

    access_level: PropertyAccessLevel
    property_definition_id: str | None = None
    ai_property: str | None = None
    organization_member_id: UUID | None = None
    role_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.property_definition_id is None) == (self.ai_property is None):
            raise ValueError("Provide exactly one of property_definition_id or ai_property.")


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


@frozen
class AccessRule:
    """One stored rule, object-level or resource-level, as resolution reads it.

    `applies` is False for a rule that resolution never uses: it names a member or a role of
    another organization, or it names both a member and a role.
    """

    resource: str
    resource_id: str | None
    access_level: str
    organization_member_id: UUID | None
    role_id: UUID | None
    applies: bool


@frozen
class ObjectAccessRuleInput:
    """One rule to keep on an object. With no member and no role, it is the object's default rule."""

    access_level: str
    organization_member_id: UUID | None = None
    role_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.organization_member_id is not None and self.role_id is not None:
            raise ValueError("Set at most one of organization_member_id or role_id.")


@frozen
class TerraformLock:
    """The state of the Terraform lock of one project. has_terraform_account is true when Terraform
    wrote access rules to the project at least once. An enabled lock with no account refuses all
    writes until that first write."""

    managed: bool
    terraform_last_applied_at: datetime | None
    has_terraform_account: bool
