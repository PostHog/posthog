from django.db import models
from django.db.models import Q
from typing import Optional
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7
from django.db.models.expressions import F
from django.db.models.functions import Coalesce


class FileSystem(models.Model):
    """
    A model representing a "file" (or folder) in our hierarchical system.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    id = models.UUIDField(primary_key=True, default=uuid7)
    path = models.TextField()
    depth = models.IntegerField(null=True, blank=True)
    type = models.CharField(max_length=100, blank=True)
    ref = models.CharField(max_length=100, null=True, blank=True)
    href = models.TextField(null=True, blank=True)
    shortcut = models.BooleanField(null=True, blank=True)
    meta = models.JSONField(default=dict, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        indexes = [
            # Index on project_id foreign key
            models.Index(fields=["project"]),
            models.Index(fields=["team"]),
            models.Index(Coalesce(F("project_id"), F("team_id")), F("path"), name="posthog_fs_project_path"),
            models.Index(Coalesce(F("project_id"), F("team_id")), F("depth"), name="posthog_fs_project_depth"),
            models.Index(
                Coalesce(F("project_id"), F("team_id")), F("type"), F("ref"), name="posthog_fs_project_typeref"
            ),
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
    created_by: Optional[User] = None,
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
        existing.save()

    if not has_existing:
        full_path = f"{base_folder}/{escape_path(name)}"
        FileSystem.objects.create(
            team=team,
            path=full_path,
            depth=len(split_path(full_path)),
            type=file_type,
            ref=ref,
            href=href,
            meta=meta,
            created_by=created_by,
            shortcut=False,
        )


def delete_file(*, team: Team, file_type: str, ref: str):
    FileSystem.objects.filter(team=team, type=file_type, ref=ref).delete()


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
