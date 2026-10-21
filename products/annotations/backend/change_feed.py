from uuid import UUID

from django.db.models import Q

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_visibility_manager

from products.annotations.backend.facade.change_feed import Change, ChangeFeed, ChangeKind, ChangeWindow, KindVisibility
from products.annotations.backend.models.annotation import Annotation
from products.error_tracking.backend.facade import api as error_tracking_api

MAX_NAME_LENGTH = 280

ACTIVITY_SCOPES: dict[ChangeKind, str] = {
    ChangeKind.FEATURE_FLAG: "FeatureFlag",
    ChangeKind.EXPERIMENT: "Experiment",
}


def _actor_name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.first_name or user.email


def _truncate(text: str | None) -> str | None:
    if text is None or len(text) <= MAX_NAME_LENGTH:
        return text
    return text[: MAX_NAME_LENGTH - 1] + "…"


def _changed_fields(detail: dict | None) -> list[str]:
    fields: list[str] = []
    for change in (detail or {}).get("changes") or []:
        field = change.get("field") if isinstance(change, dict) else None
        if field and field not in fields:
            fields.append(field)
    return fields


def _activity_changes(
    *, team_id: int, user_is_staff: bool, kind: ChangeKind, window: ChangeWindow, visibility: KindVisibility, limit: int
) -> list[Change]:
    queryset = ActivityLog.objects.select_related("user").filter(
        team_id=team_id,
        scope=ACTIVITY_SCOPES[kind],
        created_at__gte=window.start,
        created_at__lte=window.end,
    )
    if kind == ChangeKind.EXPERIMENT:
        # Holdout and shared metric changes also log under this scope, with their own ids as `item_id`.
        # A plain `exclude` also drops rows with no `type` key, because the SQL comparison is NULL there.
        queryset = queryset.filter(Q(detail__type__isnull=True) | ~Q(detail__type__in=["holdout", "shared_metric"]))
    queryset = activity_visibility_manager.apply_to_queryset(queryset, user_is_staff)
    if visibility.allowed_ids is not None:
        queryset = queryset.filter(item_id__in=visibility.allowed_ids)
    elif visibility.blocked_ids:
        queryset = queryset.exclude(item_id__in=visibility.blocked_ids)

    return [
        Change(
            kind=kind,
            timestamp=log.created_at,
            item_id=str(log.item_id),
            name=_truncate((log.detail or {}).get("name")),
            activity=log.activity,
            changed_fields=_changed_fields(log.detail),
            service=None,
            actor_name=_actor_name(log.user),
        )
        for log in queryset.order_by("-created_at")[:limit]
    ]


def _release_changes(*, team_id: int, window: ChangeWindow, limit: int) -> list[Change]:
    releases = error_tracking_api.list_releases_created_between(
        team_id, start=window.start, end=window.end, limit=limit
    )
    return [
        Change(
            kind=ChangeKind.RELEASE,
            timestamp=release.created_at,
            item_id=str(release.id),
            name=release.version,
            activity="released",
            changed_fields=[],
            service=release.project,
            actor_name=None,
        )
        for release in releases
    ]


def _annotation_changes(
    *, team_id: int, organization_id: UUID, window: ChangeWindow, visibility: KindVisibility, limit: int
) -> list[Change]:
    queryset = (
        Annotation.objects.select_related("created_by")
        .filter(Q(scope=Annotation.Scope.ORGANIZATION, organization_id=organization_id) | Q(team_id=team_id))
        .filter(deleted=False, date_marker__gte=window.start, date_marker__lte=window.end)
        # Matches the annotations list: a note on a soft-deleted insight or dashboard is hidden.
        .exclude(scope=Annotation.Scope.INSIGHT, dashboard_item__deleted=True)
        .exclude(scope=Annotation.Scope.DASHBOARD, dashboard__deleted=True)
    )
    if visibility.allowed_ids is not None:
        queryset = queryset.filter(id__in=visibility.allowed_ids)
    elif visibility.blocked_ids:
        queryset = queryset.exclude(id__in=visibility.blocked_ids)

    return [
        Change(
            kind=ChangeKind.ANNOTATION,
            timestamp=annotation.date_marker,
            item_id=str(annotation.id),
            name=_truncate(annotation.content),
            activity="annotated",
            changed_fields=[],
            service=None,
            actor_name=_actor_name(annotation.created_by),
        )
        for annotation in queryset.order_by("-date_marker", "-id")[:limit]
        if annotation.date_marker is not None
    ]


def list_changes(
    *,
    team_id: int,
    organization_id: UUID,
    user_is_staff: bool,
    window: ChangeWindow,
    visibility: dict[ChangeKind, KindVisibility],
    limit: int,
) -> ChangeFeed:
    """Merge recent production changes from every source the user may see, newest first.

    A kind missing from `visibility` is left out. Each source reads one row past `limit`,
    so `has_more` is true when any source has rows past the page.
    """
    changes: list[Change] = []
    for kind, kind_visibility in visibility.items():
        if kind in ACTIVITY_SCOPES:
            changes += _activity_changes(
                team_id=team_id,
                user_is_staff=user_is_staff,
                kind=kind,
                window=window,
                visibility=kind_visibility,
                limit=limit + 1,
            )
        elif kind == ChangeKind.RELEASE:
            changes += _release_changes(team_id=team_id, window=window, limit=limit + 1)
        elif kind == ChangeKind.ANNOTATION:
            changes += _annotation_changes(
                team_id=team_id,
                organization_id=organization_id,
                window=window,
                visibility=kind_visibility,
                limit=limit + 1,
            )

    changes.sort(key=lambda change: (change.timestamp, change.kind, change.item_id), reverse=True)
    return ChangeFeed(results=changes[:limit], has_more=len(changes) > limit)
