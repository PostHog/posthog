"""
Contract types for annotations.

Frozen dataclasses, enums and errors that cross the annotations boundary. No Django imports.
The facade accepts and returns these; the presentation layer serializes them.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from products.annotations.backend.facade.enums import AnnotationCreationType, AnnotationScope, ChangeKind


class AnnotationNotFoundError(LookupError):
    """No annotation the team can see has this id. The API answers 404."""


class AnnotationWriteRejectedError(ValueError):
    """A write breaks an annotation rule. The API answers 400 on `field` with `message`."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class AnnotationCreator:
    """The user fields an annotation response shows for its creator."""

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: dict[str, Any] | None
    role_at_organization: str | None


@dataclass(frozen=True)
class Annotation:
    id: int
    team_id: int
    organization_id: UUID | None
    content: str | None
    date_marker: datetime | None
    creation_type: AnnotationCreationType
    scope: AnnotationScope
    # The insight the annotation was created from. The API calls it `dashboard_item`.
    insight_id: int | None
    insight_short_id: str | None
    insight_name: str | None
    insight_derived_name: str | None
    dashboard_id: int | None
    dashboard_name: str | None
    created_by_id: int | None
    created_by: AnnotationCreator | None
    created_at: datetime | None
    updated_at: datetime
    deleted: bool
    emoji: str | None
    hidden_in_user_interface: bool | None


@dataclass(frozen=True)
class DatedAnnotation:
    """A non-empty annotation placed on a timeline."""

    id: int
    content: str
    scope: AnnotationScope
    # The date marker, or the creation time when the annotation has no marker.
    marked_at: datetime


@dataclass(frozen=True)
class AnnotationParent:
    """An insight or a dashboard an annotation can point at, with the fields an access check reads.

    A soft-deleted parent is still returned, with `deleted` set, because an annotation may keep a
    pointer to one.
    """

    id: int
    team_id: int
    created_by_id: int | None
    deleted: bool


@dataclass(frozen=True)
class AnnotationFilters:
    """Narrows the annotations a read can see. A None filter does not filter.

    The API applies these to every annotation route, so a filter that excludes an annotation also
    makes it unreachable for a retrieve or an update.
    """

    scope: AnnotationScope | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    # True keeps the hidden annotations. False keeps the ones shown, including those never set.
    hidden_in_user_interface: bool | None = None
    # Each term must appear in the content, ignoring case.
    search_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnnotationAccess:
    """Which annotations the access control rules let a list show the viewer.

    With `only_allowed`, the viewer has no resource-level access: the list keeps the allowed ids and
    the viewer's own annotations. Otherwise it drops the blocked ids, except the viewer's own annotations.
    """

    viewer_id: int
    only_allowed: bool
    allowed_ids: frozenset[str]
    blocked_ids: frozenset[str]


ANNOTATION_WRITE_FIELDS = frozenset(
    {
        "content",
        "date_marker",
        "creation_type",
        "scope",
        "insight_id",
        "dashboard_id",
        "deleted",
        "emoji",
        "hidden_in_user_interface",
    }
)


@dataclass(frozen=True)
class AnnotationWrite:
    """The fields a create or an update sets.

    Only the fields named in `fields_set` are written. On a create the others take the model
    defaults; on an update they keep the stored values. A field named with None clears it.
    """

    fields_set: frozenset[str]
    content: str | None = None
    date_marker: datetime | None = None
    creation_type: AnnotationCreationType | None = None
    scope: AnnotationScope | None = None
    insight_id: int | None = None
    dashboard_id: int | None = None
    deleted: bool | None = None
    emoji: str | None = None
    hidden_in_user_interface: bool | None = None

    def __post_init__(self) -> None:
        unknown = self.fields_set - ANNOTATION_WRITE_FIELDS
        if unknown:
            raise ValueError(f"Unknown annotation fields: {', '.join(sorted(unknown))}")
        for name in ("creation_type", "scope", "deleted"):
            if name in self.fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")

    def changes(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.fields_set}


# Change feed


@dataclass(frozen=True)
class ChangeWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("start must not be after end")


@dataclass(frozen=True)
class KindVisibility:
    # When set, the user may see only these object ids. Otherwise they may see all except blocked_ids.
    allowed_ids: frozenset[str] | None = None
    blocked_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    timestamp: datetime
    item_id: str
    name: str | None
    activity: str
    changed_fields: list[str]
    service: str | None
    actor_name: str | None


@dataclass(frozen=True)
class ChangeFeed:
    results: list[Change]
    has_more: bool
