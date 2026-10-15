"""
Contract types for authz.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib
variant — same syntax, same ``is_dataclass()`` compatibility (so
``DataclassSerializer`` keeps working), but with runtime type
validation on construction.
"""

from dataclasses import field, fields
from typing import Self
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import Action, Level, ResourceType


@dataclass(frozen=True, kw_only=True)
class OpenFgaStatus:
    """Whether the OpenFGA server answers, and which store and authorization model the client uses."""

    reachable: bool
    api_url: str
    store_name: str | None
    store_id: str | None
    authorization_model_id: str | None
    error: str | None


@dataclass(frozen=True, kw_only=True)
class Resource:
    """One resource, or with `id=None` every resource of `type`, for list and create checks."""

    type: ResourceType
    id: str | None = None
    project_id: int | None = None
    organization_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class Subject:
    """The principal a check or a relationship is about. Set exactly one field."""

    user_id: int | None = None
    api_key_id: str | None = None
    share_link_id: int | None = None
    export_token: str | None = field(default=None, repr=False)
    project_secret_key_id: str | None = None
    service: str | None = None
    role_id: UUID | None = None
    members_of: Resource | None = None

    def __post_init__(self) -> None:
        set_count = sum(getattr(self, subject_field.name) is not None for subject_field in fields(self))
        if set_count != 1:
            raise ValueError(f"Set exactly one field of Subject, got {set_count}.")

    @classmethod
    def members(cls, of: Resource) -> Self:
        """Every member of the project or organization that `of` names."""
        return cls(members_of=of)


@dataclass(frozen=True, kw_only=True)
class Context:
    """Request facts that conditional access rules read.

    By default each set field overrides the request's value and each `None` field keeps it.
    With `replace=True` the request context is ignored, and a `None` field means unknown.
    """

    entitlements: frozenset[str] | None = None
    channel: str | None = None
    password_verified: bool | None = None
    replace: bool = False

    @classmethod
    def override(
        cls,
        *,
        entitlements: frozenset[str] | None = None,
        channel: str | None = None,
        password_verified: bool | None = None,
    ) -> Self:
        """A context that replaces the request context instead of merging into it."""
        return cls(entitlements=entitlements, channel=channel, password_verified=password_verified, replace=True)


@dataclass(frozen=True, kw_only=True)
class CheckRequest:
    """One check in a batch. `subject=None` means the current request's subject."""

    resource: Resource
    action: Action
    subject: Subject | None = None


@dataclass(frozen=True, kw_only=True)
class AddRelationshipRequest:
    """Give the subject the relation `level` on the resource."""

    subject: Subject
    resource: Resource
    level: Level


@dataclass(frozen=True, kw_only=True)
class DeleteRelationshipRequest:
    """Remove the relation `level` from the subject, or every relation when `level=None`."""

    subject: Subject
    resource: Resource
    level: Level | None = None


@dataclass(frozen=True, kw_only=True)
class ObjectIds:
    """IDs of the objects a subject may act on. `complete=False` means the set was capped."""

    ids: frozenset[str]
    complete: bool


@dataclass(frozen=True, kw_only=True)
class Explanation:
    """The decision of one check, and the rules it went through to reach it, in order."""

    allowed: bool
    path: tuple[str, ...]
