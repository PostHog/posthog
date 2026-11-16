"""Reads and writes of annotations, and the rules every write follows."""

from collections.abc import Callable, Collection
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from django.db.models import F, Q, QuerySet
from django.db.models.functions import Coalesce

from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.annotations.backend.facade.contracts import (
    AnnotationAccess,
    AnnotationFilters,
    AnnotationNotFoundError,
    AnnotationParent,
    AnnotationWrite,
    AnnotationWriteRejectedError,
)
from products.annotations.backend.facade.enums import AnnotationScope
from products.annotations.backend.models.annotation import Annotation
from products.dashboards.backend.facade import api as dashboards_api
from products.product_analytics.backend.facade.models import Insight

_PARENT_FIELDS = ("id", "team_id", "created_by_id", "deleted")


def _with_relations() -> QuerySet[Annotation]:
    return Annotation.objects.select_related("dashboard_item").select_related("dashboard").select_related("created_by")


def _visible(
    queryset: QuerySet[Annotation],
    *,
    team_id: int,
    organization_id: UUID,
    filters: AnnotationFilters,
    include_deleted: bool,
    access: AnnotationAccess | None = None,
) -> QuerySet[Annotation]:
    """The annotations a team can see: its own, and the organization-scoped ones of its organization."""
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    # An annotation scoped to a soft-deleted insight or dashboard is hidden, so it cannot be edited or
    # restored while its parent is deleted, and it comes back when the parent is restored. The rule is
    # gated on scope: every annotation records the insight and dashboard it was created from, so a
    # project- or organization-scoped one would otherwise disappear with that parent.
    queryset = queryset.exclude(scope=AnnotationScope.INSIGHT, dashboard_item__deleted=True).exclude(
        scope=AnnotationScope.DASHBOARD, dashboard__deleted=True
    )
    if filters.scope is not None:
        queryset = queryset.filter(scope=filters.scope)
    if filters.date_from is not None:
        queryset = queryset.filter(date_marker__gte=filters.date_from)
    if filters.date_to is not None:
        queryset = queryset.filter(date_marker__lte=filters.date_to)
    if filters.hidden_in_user_interface is True:
        queryset = queryset.filter(hidden_in_user_interface=True)
    elif filters.hidden_in_user_interface is False:
        queryset = queryset.filter(Q(hidden_in_user_interface=False) | Q(hidden_in_user_interface__isnull=True))
    queryset = queryset.filter(
        Q(scope=AnnotationScope.ORGANIZATION, organization_id=organization_id) | Q(team_id=team_id)
    )
    if access is not None:
        if access.only_allowed:
            queryset = queryset.filter(Q(id__in=access.allowed_ids) | Q(created_by_id=access.viewer_id))
        elif access.blocked_ids:
            queryset = queryset.exclude(Q(id__in=access.blocked_ids) & ~Q(created_by_id=access.viewer_id))
    if filters.search_terms:
        queryset = queryset.filter(Q(*(Q(content__icontains=term) for term in filters.search_terms)))
    return queryset


def list_annotations(
    *,
    team_id: int,
    organization_id: UUID,
    filters: AnnotationFilters,
    page: PageRequest,
    access: AnnotationAccess | None = None,
) -> Page[Annotation]:
    # `date_marker` alone is not a total order, so limit-offset pages could repeat or drop rows.
    queryset = strict_fetch(_with_relations().order_by("-date_marker", "-id"))
    queryset = _visible(
        queryset,
        team_id=team_id,
        organization_id=organization_id,
        filters=filters,
        include_deleted=False,
        access=access,
    )
    return select_page(queryset, page)


def get_annotation(
    *,
    team_id: int,
    organization_id: UUID,
    annotation_id: int,
    filters: AnnotationFilters,
    include_deleted: bool,
) -> Annotation:
    queryset = _visible(
        _with_relations(),
        team_id=team_id,
        organization_id=organization_id,
        filters=filters,
        include_deleted=include_deleted,
    )
    try:
        return queryset.get(pk=annotation_id)
    except Annotation.DoesNotExist:
        raise AnnotationNotFoundError(annotation_id)


def find_dashboard_parent(*, team_id: int, dashboard_id: int) -> AnnotationParent | None:
    dashboard = dashboards_api.get_dashboard(team_id=team_id, dashboard_id=dashboard_id, include_deleted=True)
    if dashboard is None:
        return None
    return AnnotationParent(
        id=dashboard.id, team_id=dashboard.team_id, created_by_id=dashboard.created_by_id, deleted=dashboard.deleted
    )


def find_insight_parent(*, team_id: int, insight_id: int) -> AnnotationParent | None:
    rows = Insight.objects_including_soft_deleted.filter(team_id=team_id, pk=insight_id).values(*_PARENT_FIELDS)
    return next((AnnotationParent(**row) for row in rows), None)


def _stored_parent(parent: Insight | None) -> AnnotationParent | None:
    if parent is None:
        return None
    return AnnotationParent(
        id=parent.pk, team_id=parent.team_id, created_by_id=parent.created_by_id, deleted=parent.deleted
    )


def _parent_after_write(
    *,
    write: AnnotationWrite,
    field: str,
    stored: AnnotationParent | None,
    find: Callable[[int], AnnotationParent | None],
    not_found: str,
) -> AnnotationParent | None:
    """The parent an annotation has after the write. A field the write leaves out keeps the stored parent.

    A new pointer must name a parent of the team that is not soft-deleted. The pointer the annotation
    already stores may name a soft-deleted one, because clients echo it back on every write.
    """
    if field not in write.fields_set:
        return stored
    new_id = getattr(write, field)
    if new_id is None:
        return None
    parent = find(new_id)
    if parent is None or (parent.deleted and (stored is None or parent.id != stored.id)):
        raise AnnotationWriteRejectedError(field, not_found)
    return parent


def _check_write(*, team_id: int, current: Annotation | None, write: AnnotationWrite) -> dict[str, Any]:
    """Apply the parent rules to a write, and return the model fields it sets."""
    dashboard = _parent_after_write(
        write=write,
        field="dashboard_id",
        stored=find_dashboard_parent(team_id=team_id, dashboard_id=current.dashboard_id)
        if current is not None and current.dashboard_id is not None
        else None,
        find=lambda dashboard_id: find_dashboard_parent(team_id=team_id, dashboard_id=dashboard_id),
        not_found="Dashboard not found.",
    )
    insight = _parent_after_write(
        write=write,
        field="insight_id",
        stored=_stored_parent(current.dashboard_item) if current is not None else None,
        find=lambda insight_id: find_insight_parent(team_id=team_id, insight_id=insight_id),
        not_found="Insight not found.",
    )

    scope = write.scope if "scope" in write.fields_set else None
    # A create checks only an explicit scope, because rows created without one take the model default
    # and have no insight. An update checks the scope the row will have, so clearing the parent is
    # caught too. A row already stored without its parent, such as a default row or one whose
    # dashboard was hard-deleted, stays editable, because the UI echoes its scope back.
    checked_scope = scope if current is None else scope or current.scope
    if (
        checked_scope == AnnotationScope.INSIGHT
        and insight is None
        and not (current is not None and current.scope == checked_scope and current.dashboard_item_id is None)
    ):
        raise AnnotationWriteRejectedError(
            "insight_id", "Set `dashboard_item` to the insight ID when the scope is `dashboard_item`."
        )
    if (
        checked_scope == AnnotationScope.DASHBOARD
        and dashboard is None
        and not (current is not None and current.scope == checked_scope and current.dashboard_id is None)
    ):
        raise AnnotationWriteRejectedError(
            "dashboard_id", "Set `dashboard_id` to the dashboard ID when the scope is `dashboard`."
        )

    # A row whose own scope points at a soft-deleted parent is hidden from every read, so accepting
    # one would strand a row that nothing can list, edit or delete. Project- and organization-scoped
    # rows keep their pointers, which only show where the annotation was created.
    effective_scope = scope or (current.scope if current is not None else AnnotationScope.INSIGHT)
    if effective_scope == AnnotationScope.INSIGHT and insight is not None and insight.deleted:
        raise AnnotationWriteRejectedError(
            "insight_id", "This insight is deleted. Restore it, or pick a different scope."
        )
    if effective_scope == AnnotationScope.DASHBOARD and dashboard is not None and dashboard.deleted:
        raise AnnotationWriteRejectedError(
            "dashboard_id", "This dashboard is deleted. Restore it, or pick a different scope."
        )

    # Plain values, not enum members, so the row holds what it held before the write went through the facade.
    changes = {name: value.value if isinstance(value, Enum) else value for name, value in write.changes().items()}
    if "insight_id" in changes:
        changes["dashboard_item_id"] = changes.pop("insight_id")
    return changes


def create_annotation(
    *, team_id: int, organization_id: UUID, created_by_id: int | None, write: AnnotationWrite
) -> Annotation:
    changes = _check_write(team_id=team_id, current=None, write=write)
    return Annotation.objects.create(
        organization_id=organization_id, team_id=team_id, created_by_id=created_by_id, **changes
    )


def update_annotation(
    *, team_id: int, organization_id: UUID, annotation_id: int, write: AnnotationWrite, include_deleted: bool
) -> Annotation:
    annotation = get_annotation(
        team_id=team_id,
        organization_id=organization_id,
        annotation_id=annotation_id,
        filters=AnnotationFilters(),
        include_deleted=include_deleted,
    )
    changes = _check_write(team_id=team_id, current=annotation, write=write)
    # The project the write comes from takes the annotation over, so an organization-scoped one that is
    # narrowed to a project stays visible in the project it was edited from.
    annotation.team_id = team_id
    for name, value in changes.items():
        setattr(annotation, name, value)
    annotation.save()
    return annotation


def create_project_annotation(
    *, team_id: int, organization_id: UUID, created_by_id: int | None, content: str, date_marker: datetime
) -> Annotation:
    return Annotation.objects.create(
        team_id=team_id,
        organization_id=organization_id,
        created_by_id=created_by_id,
        content=content,
        date_marker=date_marker,
        scope=AnnotationScope.PROJECT,
    )


def list_dated_annotations(
    *, team_id: int, organization_id: UUID, start: datetime, end: datetime, limit: int
) -> list[tuple[Annotation, datetime]]:
    """Non-empty annotations the team can see, marked in the window, newest first.

    Every scope counts, unlike the AI context of one insight or dashboard. An annotation without a
    date marker is placed at its creation time.
    """
    annotations = (
        Annotation.objects.filter(
            Q(team_id=team_id) | Q(scope=AnnotationScope.ORGANIZATION, organization_id=organization_id),
            deleted=False,
            content__isnull=False,
        )
        .exclude(content="")
        .annotate(effective_date=Coalesce(F("date_marker"), F("created_at")))
        .filter(effective_date__gte=start, effective_date__lte=end)
        .order_by("-effective_date")[:limit]
    )
    return [(annotation, annotation.effective_date) for annotation in annotations]


def annotation_ids_in_team(*, team_id: int, annotation_ids: Collection[int]) -> set[int]:
    return set(Annotation.objects.filter(team_id=team_id, id__in=annotation_ids).values_list("id", flat=True))
