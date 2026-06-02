from datetime import datetime
from typing import Optional

from django.db import models
from django.db.models import Q
from django.db.models.expressions import F
from django.utils import timezone

from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


class FileSystem(models.Model):
    """
    A model representing a "file" (or folder) in our hierarchical system.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid7)
    path = models.TextField()
    depth = models.IntegerField(null=True, blank=True)
    type = models.CharField(max_length=100, blank=True)
    ref = models.CharField(max_length=100, null=True, blank=True)
    href = models.TextField(null=True, blank=True)
    shortcut = models.BooleanField(null=True, blank=True)
    meta = models.JSONField(default=dict, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    # DEPRECATED/UNUSED. It's all based on just the team_id.
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["team"]),
            models.Index(F("team_id"), F("path"), name="posthog_fs_team_path"),
            models.Index(F("team_id"), F("depth"), name="posthog_fs_team_depth"),
            models.Index(F("team_id"), F("type"), F("ref"), name="posthog_fs_team_typeref"),
        ]

    def __str__(self):
        return self.path


def create_or_update_file(
    *,
    team: Team,
    base_folder: str,
    name: str,
    file_type: str,
    ref: str,
    href: str,
    meta: dict,
    created_at: Optional[datetime] = None,
    created_by_id: Optional[int] = None,
):
    has_existing = False
    all_existing = FileSystem.objects.filter(team=team, type=file_type, ref=ref).filter(~Q(shortcut=True)).all()
    for existing in all_existing:
        has_existing = True
        segments = split_path(existing.path)
        segments[-1] = escape_path(name)
        new_path = join_path(segments)
        existing.path = new_path
        existing.depth = len(segments)
        existing.href = href
        existing.meta = meta
        if created_at:
            existing.created_at = created_at
        if created_by_id and existing.created_by_id != created_by_id:
            existing.created_by_id = created_by_id
        existing.save()

    if has_existing:
        path = escape_path(name)
        shortcuts = (
            FileSystemShortcut.objects.filter(team=team, type=file_type, ref=ref)
            .filter(~(Q(path=path) & Q(href=href)))
            .all()
        )
        for shortcut in shortcuts:
            shortcut.path = path
            shortcut.href = href
            shortcut.save()
    else:
        full_path = f"{base_folder}/{escape_path(name)}"
        FileSystem.objects.create(
            team=team,
            path=full_path,
            depth=len(split_path(full_path)),
            type=file_type,
            ref=ref,
            href=href,
            meta=meta,
            shortcut=False,
            created_by_id=created_by_id,
            created_at=created_at or timezone.now(),
        )


def delete_file(*, team: Team, file_type: str, ref: str):
    count, _ = FileSystem.objects.filter(team=team, type=file_type, ref=ref).delete()
    if count > 0:
        FileSystemShortcut.objects.filter(team=team, type=file_type, ref=ref).delete()


def split_path(path: str) -> list[str]:
    segments = []
    current = ""
    i = 0
    while i < len(path):
        # If we encounter a backslash, and the next char is either / or \
        if path[i] == "\\" and i < len(path) - 1 and path[i + 1] in ["/", "\\"]:
            current += path[i + 1]
            i += 2
            continue
        elif path[i] == "/":
            segments.append(current)
            current = ""
        else:
            current += path[i]
        i += 1

    # Push any remaining part of the path into segments
    segments.append(current)

    # Filter out empty segments
    return [s for s in segments if s != ""]


def escape_path(path: str) -> str:
    # Replace backslash with double-backslash, and forward slash with backslash-slash
    path = path.replace("\\", "\\\\")
    path = path.replace("/", "\\/")
    return path


def join_path(paths: list[str]) -> str:
    # Join all segments using '/', while escaping each segment
    return "/".join(escape_path(segment) for segment in paths)
