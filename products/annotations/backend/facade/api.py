"""Facade API for the annotations product — the surface other products and the product's own views may import.

Accepts ids and contracts, returns contracts, never ORM instances.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from django.utils import timezone

from posthog.models import Team, User
from posthog.paging import Page, PageRequest

from products.annotations.backend.facade import contracts, enums
from products.annotations.backend.logic import ai_context, annotations, change_feed
from products.annotations.backend.models.annotation import Annotation

__all__ = [
    "annotation_ids_in_team",
    "build_snapshot_annotations_block",
    "create_annotation",
    "create_project_annotation",
    "find_dashboard_parent",
    "find_insight_parent",
    "get_annotation",
    "list_annotations",
    "list_changes",
    "list_dated_annotations",
    "update_annotation",
]


def _to_creator(user: User | None) -> contracts.AnnotationCreator | None:
    if user is None:
        return None
    return contracts.AnnotationCreator(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _to_annotation(annotation: Annotation) -> contracts.Annotation:
    return contracts.Annotation(
        id=annotation.id,
        team_id=annotation.team_id,
        organization_id=annotation.organization_id,
        content=annotation.content,
        date_marker=annotation.date_marker,
        creation_type=enums.AnnotationCreationType(annotation.creation_type),
        scope=enums.AnnotationScope(annotation.scope),
        insight_id=annotation.dashboard_item_id,
        insight_short_id=annotation.insight_short_id,
        insight_name=annotation.insight_name,
        insight_derived_name=annotation.insight_derived_name,
        dashboard_id=annotation.dashboard_id,
        dashboard_name=annotation.dashboard_name,
        created_by_id=annotation.created_by_id,
        created_by=_to_creator(annotation.created_by),
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
        deleted=annotation.deleted,
        emoji=annotation.emoji,
        hidden_in_user_interface=annotation.hidden_in_user_interface,
    )


def list_annotations(
    *,
    team_id: int,
    organization_id: UUID,
    filters: contracts.AnnotationFilters,
    page: PageRequest,
    access: contracts.AnnotationAccess | None = None,
) -> Page[contracts.Annotation]:
    """One page of the live annotations the team can see, newest `date_marker` first.

    The team sees its own annotations and the organization-scoped ones of its organization. An
    annotation scoped to a soft-deleted insight or dashboard is left out. `access` narrows the page
    and its count to what the viewer's access control rules allow.
    """
    return annotations.list_annotations(
        team_id=team_id, organization_id=organization_id, filters=filters, page=page, access=access
    ).map(_to_annotation)


def get_annotation(
    *,
    team_id: int,
    organization_id: UUID,
    annotation_id: int,
    filters: contracts.AnnotationFilters | None = None,
    include_deleted: bool = False,
) -> contracts.Annotation:
    """One annotation the team can see. Raises `AnnotationNotFoundError` when there is none.

    A soft-deleted annotation is found only with `include_deleted`, which is how one is restored.
    """
    return _to_annotation(
        annotations.get_annotation(
            team_id=team_id,
            organization_id=organization_id,
            annotation_id=annotation_id,
            filters=filters or contracts.AnnotationFilters(),
            include_deleted=include_deleted,
        )
    )


def find_dashboard_parent(*, team_id: int, dashboard_id: int) -> contracts.AnnotationParent | None:
    """The team's dashboard with this id, soft-deleted or not, as an annotation parent."""
    return annotations.find_dashboard_parent(team_id=team_id, dashboard_id=dashboard_id)


def find_insight_parent(*, team_id: int, insight_id: int) -> contracts.AnnotationParent | None:
    """The team's insight with this id, soft-deleted or not, as an annotation parent."""
    return annotations.find_insight_parent(team_id=team_id, insight_id=insight_id)


def create_annotation(
    *, team_id: int, organization_id: UUID, created_by_id: int | None, write: contracts.AnnotationWrite
) -> contracts.Annotation:
    """Create an annotation in the team. Raises `AnnotationWriteRejectedError` when the write breaks a rule.

    A new insight or dashboard pointer must name a parent of the team that is not soft-deleted, and
    an insight or a dashboard scope needs the matching parent.
    """
    annotation = annotations.create_annotation(
        team_id=team_id, organization_id=organization_id, created_by_id=created_by_id, write=write
    )
    return _to_annotation(annotation)


def update_annotation(
    *,
    team_id: int,
    organization_id: UUID,
    annotation_id: int,
    write: contracts.AnnotationWrite,
    include_deleted: bool = False,
) -> contracts.Annotation:
    """Change the fields the write names. The annotation moves to `team_id`, the project it is edited from.

    Raises `AnnotationNotFoundError` when the team cannot see the annotation, and
    `AnnotationWriteRejectedError` when the write breaks a rule. Pass `include_deleted` to restore a
    soft-deleted annotation.
    """
    annotation = annotations.update_annotation(
        team_id=team_id,
        organization_id=organization_id,
        annotation_id=annotation_id,
        write=write,
        include_deleted=include_deleted,
    )
    return _to_annotation(annotation)


def create_project_annotation(
    team_id: int, user_id: int | None, *, content: str, date_marker: datetime | None = None
) -> int:
    """Create a project-scoped annotation as the user, returning its id.

    ``date_marker`` defaults to the creation time when omitted — a null marker
    would keep the annotation off every chart and out of AI context, which is
    never what a project annotation wants.
    """
    team = Team.objects.get(id=team_id)
    annotation = annotations.create_project_annotation(
        team_id=team_id,
        organization_id=team.organization_id,
        created_by_id=user_id,
        content=content,
        date_marker=date_marker if date_marker is not None else timezone.now(),
    )
    return annotation.id


def list_dated_annotations(
    *, team_id: int, organization_id: UUID, start: datetime, end: datetime, limit: int
) -> list[contracts.DatedAnnotation]:
    """Non-empty, live annotations the team can see, marked between `start` and `end`, newest first.

    Every scope counts. An annotation without a date marker is placed at its creation time.
    """
    return [
        contracts.DatedAnnotation(
            id=annotation.id,
            content=annotation.content,
            scope=enums.AnnotationScope(annotation.scope),
            marked_at=marked_at,
        )
        for annotation, marked_at in annotations.list_dated_annotations(
            team_id=team_id, organization_id=organization_id, start=start, end=end, limit=limit
        )
        # The query leaves out null content, but a concurrent update can null it before the row is read.
        if annotation.content is not None
    ]


def annotation_ids_in_team(*, team_id: int, annotation_ids: Collection[int]) -> set[int]:
    """The ids among `annotation_ids` of annotations stored in the team, deleted or not."""
    return annotations.annotation_ids_in_team(team_id=team_id, annotation_ids=annotation_ids)


def build_snapshot_annotations_block(
    team: Team,
    content_snapshots: list[dict],
    *,
    dashboard_id: int | None = None,
    insight_ids: list[int] | None = None,
) -> str:
    """The prompt block listing the annotations in the window subscription content snapshots cover.

    The window is the widest absolute date range the snapshots' insights were rendered for. Project-
    and organization-scoped annotations always count, and dashboard- and insight-scoped ones count
    when they are attached to the given dashboard or insights. Returns `""` when there is nothing to show.
    """
    return ai_context.build_annotations_block(
        team,
        ai_context.resolve_snapshot_date_range(content_snapshots),
        dashboard_id=dashboard_id,
        insight_ids=insight_ids,
    )


def list_changes(
    *,
    team_id: int,
    organization_id: UUID,
    user_is_staff: bool,
    window: contracts.ChangeWindow,
    visibility: dict[enums.ChangeKind, contracts.KindVisibility],
    limit: int,
) -> contracts.ChangeFeed:
    """Recent production changes the caller may see, newest first. A kind missing from `visibility` is left out."""
    return change_feed.list_changes(
        team_id=team_id,
        organization_id=organization_id,
        user_is_staff=user_is_staff,
        window=window,
        visibility=visibility,
        limit=limit,
    )
