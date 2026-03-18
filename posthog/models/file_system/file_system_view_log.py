from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional, cast

from django.db import IntegrityError, models
from django.db.models import F, FilteredRelation, Q, QuerySet
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

    update_kwargs = {
        "team_id": resolved_team_id,
        "user_id": user.id,
        "type": representation.type,
        "ref": str(representation.ref),
    }

    updated = FileSystemViewLog.objects.filter(**update_kwargs).update(viewed_at=now)

    if updated:
        return

    try:
        FileSystemViewLog.objects.create(viewed_at=now, **update_kwargs)
    except IntegrityError:
        # Another request may have created the row after our update attempt.
        FileSystemViewLog.objects.filter(**update_kwargs).update(viewed_at=now)


def annotate_file_system_with_view_logs(
    *, team_id: int, user_id: int, queryset: Optional[QuerySet] = None
) -> QuerySet[FileSystem]:
    queryset = queryset or FileSystem.objects.all()
    base_qs = queryset.filter(team_id=team_id).alias(
        matching_view_logs=FilteredRelation(
            "team__filesystemviewlog",
            condition=(
                Q(team__filesystemviewlog__user_id=user_id)
                & Q(team__filesystemviewlog__type=models.F("type"))
                & Q(team__filesystemviewlog__ref=models.F("ref"))
            ),
        )
    )

    return base_qs.annotate(last_viewed_at=F("matching_view_logs__viewed_at"))


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
