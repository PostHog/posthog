from __future__ import annotations

from collections.abc import Sequence
from dataclasses import is_dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional, cast

from django.db import IntegrityError, models
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models.user import User


class FileSystemViewLog(UUIDModel):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    type = models.CharField(max_length=150)
    ref = models.CharField(max_length=200)
    viewed_at = models.DateTimeField(default=timezone.now)
    # Product surface this view belongs to (e.g. "web", "desktop"). NULL == DEFAULT_SURFACE.
    # Not part of the unique constraint below: a (type, ref) item is exclusive to one surface,
    # so (team, user, type, ref) already identifies a view uniquely. The column only lets us
    # filter Recents to a single surface without joining back to FileSystem.
    surface = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "user", "-viewed_at"], name="posthog_fsvl_recent_user_views"),
            models.Index(fields=["team", "type", "ref", "-viewed_at"], name="posthog_fsvl_recent_item_views"),
        ]
        constraints = [
            models.UniqueConstraint(fields=("team", "user", "type", "ref"), name="posthog_fsvl_unique_user_item")
        ]


@receiver(post_delete, sender=FileSystem)
def _drop_view_logs_when_file_deleted(sender, instance: FileSystem, **kwargs) -> None:
    # When a file (not a folder or shortcut) is removed, drop the matching view logs so
    # the Recents sidebar can't surface a dead reference. Shortcuts share (type, ref) with
    # their canonical file, so we only act when the canonical row is gone.
    if not instance.ref or instance.type == "folder" or instance.shortcut:
        return
    surface = instance.surface or DEFAULT_SURFACE
    if (
        FileSystem.objects.filter(surface_q(surface), team_id=instance.team_id, type=instance.type, ref=instance.ref)
        .exclude(shortcut=True)
        .exists()
    ):
        return
    FileSystemViewLog.objects.filter(
        surface_q(surface), team_id=instance.team_id, type=instance.type, ref=instance.ref
    ).delete()


def log_file_system_view(
    *,
    user: Optional[User],
    obj: FileSystemRepresentation | object,
    team_id: Optional[int] = None,
    viewed_at: Optional[datetime] = None,
) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        return

    resolved = resolve_representation(obj, team_id=team_id)
    if resolved is None:
        return

    resolved_team_id, representation = resolved

    now = viewed_at or timezone.now()

    # The (team, user, type, ref) unique constraint allows one view-log row per item, so surface
    # is not part of the lookup. The same (type, ref) can exist in more than one surface, so we
    # refresh `surface` on every view: the row reflects the most recent view's surface, keeping
    # Recents (filtered per-surface) and the delete-cleanup signal accurate. Legacy rows are NULL (== web).
    update_kwargs = {
        "team_id": resolved_team_id,
        "user_id": user.id,
        "type": representation.type,
        "ref": str(representation.ref),
    }
    surface = getattr(representation, "surface", DEFAULT_SURFACE)

    updated = FileSystemViewLog.objects.filter(**update_kwargs).update(viewed_at=now, surface=surface)

    if updated:
        return

    try:
        FileSystemViewLog.objects.create(viewed_at=now, surface=surface, **update_kwargs)
    except IntegrityError:
        # Another request may have created the row after our update attempt.
        FileSystemViewLog.objects.filter(**update_kwargs).update(viewed_at=now, surface=surface)


def recent_view_logs(
    *,
    team_id: int,
    user_id: int,
    surface: str = DEFAULT_SURFACE,
    type: Optional[str] = None,
    exclude_types: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    descending: bool = True,
) -> QuerySet[FileSystemViewLog]:
    """A user's view-log rows for one surface, newest first by default.

    Served end-to-end by the ``(team, user, -viewed_at)`` index: no join to FileSystem and no
    sort on a computed column. This is the single query behind both Recents and the per-scene
    "last viewed" markers. ``descending=False`` orders oldest-first; the slice then happens at the
    query level so ``limit`` always returns the globally oldest/newest rows, never a re-sorted page.
    """
    queryset = FileSystemViewLog.objects.filter(surface_q(surface), team_id=team_id, user_id=user_id)
    if type is not None:
        queryset = queryset.filter(type=type)
    if exclude_types:
        queryset = queryset.exclude(type__in=list(exclude_types))
    queryset = queryset.order_by("-viewed_at" if descending else "viewed_at")
    if limit is not None:
        queryset = queryset[:limit]
    return queryset


def get_recent_file_system_items(
    *,
    team_id: int,
    user_id: int,
    surface: str = DEFAULT_SURFACE,
    limit: Optional[int] = None,
    exclude_types: Optional[Sequence[str]] = ("folder",),
    file_system_queryset: Optional[QuerySet[FileSystem]] = None,
    descending: bool = True,
) -> list[FileSystem]:
    """Recently-viewed FileSystem rows for a user, newest first by default.

    View-log-first: read the recent ``(type, ref)`` keys from the indexed view log, then hydrate
    the canonical FileSystem rows for exactly those keys. This replaces a left join plus an
    ``ORDER BY`` on a computed ``last_viewed_at`` column, which forced a full scan and sort of the
    team's entire tree on every homepage/search load.

    ``file_system_queryset`` lets callers pre-scope the hydration (e.g. apply access control)
    before the ``(type, ref)`` keys are matched. ``descending`` is threaded down to the view-log
    query so the ``limit`` slice picks the globally oldest/newest views, not a re-sorted page.
    """
    log_rows = list(
        recent_view_logs(
            team_id=team_id,
            user_id=user_id,
            surface=surface,
            exclude_types=exclude_types,
            limit=limit,
            descending=descending,
        ).values_list("type", "ref", "viewed_at")
    )
    if not log_rows:
        return []

    # The (team, user, type, ref) unique constraint guarantees one row per key, so no dedup needed.
    key_filter = Q()
    for row_type, row_ref, _ in log_rows:
        key_filter |= Q(type=row_type, ref=row_ref)

    base_queryset = (
        file_system_queryset
        if file_system_queryset is not None
        else FileSystem.objects.filter(surface_q(surface), team_id=team_id)
    )
    rows_by_key: dict[tuple[str, Optional[str]], FileSystem] = {
        (row.type, row.ref): row
        for row in base_queryset.filter(key_filter).exclude(shortcut=True).select_related("created_by")
    }

    ordered: list[FileSystem] = []
    for row_type, row_ref, viewed_at in log_rows:
        row = rows_by_key.get((row_type, row_ref))
        if row is not None:
            row.last_viewed_at = viewed_at  # type: ignore[attr-defined]
            ordered.append(row)
    return ordered


def resolve_representation(
    obj: FileSystemRepresentation | object,
    *,
    team_id: Optional[int] = None,
) -> tuple[int, FileSystemRepresentation] | None:
    if isinstance(obj, FileSystemRepresentation):
        if team_id is None:
            raise ValueError("Team id must be provided when using a FileSystemRepresentation directly.")
        return team_id, obj

    if hasattr(obj, "get_file_system_representation"):
        team = getattr(obj, "team", None)
        if team is None:
            return None
        representation = cast(FileSystemRepresentation, obj.get_file_system_representation())
        return team.id, representation

    if is_dataclass(obj) and isinstance(obj, FileSystemRepresentation):
        if team_id is None:
            raise ValueError("Team id must be provided when using a FileSystemRepresentation directly.")
        return team_id, obj

    return None
