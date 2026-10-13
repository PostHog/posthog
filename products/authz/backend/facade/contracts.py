"""
Contract types for authz.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib
variant — same syntax, same ``is_dataclass()`` compatibility (so
``DataclassSerializer`` keeps working), but with runtime type
validation on construction.
"""

import hashlib
from dataclasses import field, fields
from typing import Self
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import Action, FilterKind, Level, ResourceType


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
class ResourceIds:
    """Ids of the resources a subject may act on. `complete=False` means the set was capped."""

    ids: frozenset[str]
    complete: bool


@dataclass(frozen=True, kw_only=True)
class AccessFilter:
    """The rows of one resource type a subject may act on, as a residual the caller pushes into its own query.

    `kind` says how `ids` apply: ALL and NONE carry no ids, ONLY keeps just `ids`, EXCEPT drops `ids`.
    `creator_exempt` means rows the subject created stay visible whatever `kind` says. The adapter that
    applies the filter supplies the creator column, because only the enforcement point knows it.
    `complete=False` means the id set was capped. The filter is then NONE, so the caller fails closed.
    """

    resource_type: ResourceType
    action: Action
    kind: FilterKind
    ids: frozenset[str] = frozenset()
    creator_exempt: bool = False
    complete: bool = True

    def __post_init__(self) -> None:
        if self.kind in (FilterKind.ALL, FilterKind.NONE) and self.ids:
            raise ValueError(f"An {self.kind.value} filter carries no ids, got {len(self.ids)}.")
        if self.kind in (FilterKind.ONLY, FilterKind.EXCEPT) and not self.ids:
            raise ValueError(f"An {self.kind.value} filter needs at least one id.")
        if not self.complete and self.kind != FilterKind.NONE:
            raise ValueError("A capped filter must be NONE so the caller fails closed.")

    @property
    def restricts(self) -> bool:
        """Whether applying the filter can remove rows."""
        return self.kind != FilterKind.ALL

    def allows(self, id: str, *, created_by_user_id: int | None = None, subject_user_id: int | None = None) -> bool:
        """Whether one row passes the filter. Same rule as the QuerySet and HogQL adapters, for one object."""
        if self.creator_exempt and subject_user_id is not None and created_by_user_id == subject_user_id:
            return True
        if self.kind == FilterKind.ALL:
            return True
        if self.kind == FilterKind.NONE:
            return False
        return (id in self.ids) == (self.kind == FilterKind.ONLY)

    def fingerprint(self) -> str:
        """Stable digest of the decision, for query cache keys."""
        payload = "|".join(
            (self.resource_type.value, self.action.value, self.kind.value, ",".join(sorted(self.ids)))
            + (("creator",) if self.creator_exempt else ())
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True, kw_only=True)
class Explanation:
    """The decision of one check, and the rules it went through to reach it, in order."""

    allowed: bool
    path: tuple[str, ...]
