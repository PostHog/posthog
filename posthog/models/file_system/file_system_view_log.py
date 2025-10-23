from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional, cast

from django.db import models
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

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

    class Meta:
        indexes = [
            models.Index(fields=["team", "user", "-viewed_at"], name="posthog_fsvl_recent_user_views"),
            models.Index(fields=["team", "type", "ref", "-viewed_at"], name="posthog_fsvl_recent_item_views"),
        ]
        constraints = [
            models.UniqueConstraint(fields=("team", "user", "type", "ref"), name="posthog_fsvl_unique_user_item")
        ]


@dataclass(frozen=True)
class RecentViewer:
    user_id: int
    last_viewed_at: datetime


def log_file_system_view(
    *,
    user: Optional[User],
    obj: FileSystemRepresentation | object,
    team_id: Optional[int] = None,
    viewed_at: Optional[datetime] = None,
) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        return

    resolved = _resolve_representation(obj, team_id=team_id)
    if resolved is None:
        return

    resolved_team_id, representation = resolved

    now = viewed_at or timezone.now()

    FileSystemViewLog.objects.update_or_create(
        team_id=resolved_team_id,
        user_id=user.id,
        type=representation.type,
        ref=str(representation.ref),
        defaults={"viewed_at": now},
    )


def annotate_file_system_with_view_logs(
    *, team_id: int, user_id: int, queryset: Optional[QuerySet] = None
) -> QuerySet[FileSystem]:
    queryset = queryset or FileSystem.objects.all()
    base_qs = queryset.filter(team_id=team_id)

    view_logs_filter = Q(team__filesystemviewlog__user_id=user_id)
    view_logs_filter &= Q(team__filesystemviewlog__type=models.F("type"))
    view_logs_filter &= Q(team__filesystemviewlog__ref=models.F("ref"))

    return base_qs.annotate(
        last_viewed_at=Max(
            "team__filesystemviewlog__viewed_at",
            filter=view_logs_filter,
        )
    )


def get_recent_file_system_items(*, team_id: int, user_id: int, limit: Optional[int] = None) -> QuerySet[FileSystem]:
    queryset = annotate_file_system_with_view_logs(
        team_id=team_id,
        user_id=user_id,
        queryset=FileSystem.objects.filter(Q(shortcut=False) | Q(shortcut__isnull=True)),
    )

    queryset = queryset.order_by(models.F("last_viewed_at").desc(nulls_last=True))

    if limit is not None:
        queryset = queryset[:limit]

    return queryset


def get_recent_viewers_for_resource(
    *,
    team_id: int,
    file_type: str,
    ref: str,
    since: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> list[RecentViewer]:
    view_qs = FileSystemViewLog.objects.filter(team_id=team_id, type=file_type, ref=str(ref))

    if since is not None:
        view_qs = view_qs.filter(viewed_at__gte=since)

    aggregated = (
        view_qs.values("user_id")
        .annotate(last_viewed_at=Max("viewed_at"))
        .order_by(models.F("last_viewed_at").desc(nulls_last=True))
    )

    if limit is not None:
        aggregated = aggregated[:limit]

    return [RecentViewer(user_id=row["user_id"], last_viewed_at=row["last_viewed_at"]) for row in aggregated]


def _resolve_representation(
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
