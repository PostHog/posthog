from django.db import models
from typing import Optional
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7, TeamProjectMixin
from django.db.models.expressions import F
from django.db.models.functions import Coalesce
from django.db.models import QuerySet


class FileSystem(TeamProjectMixin, models.Model):
    """
    A model representing a "file" (or folder) in our hierarchical system.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    id = models.UUIDField(primary_key=True, default=uuid7)
    path = models.TextField()
    depth = models.IntegerField(null=True, blank=True)
    type = models.CharField(max_length=100, blank=True)
    ref = models.CharField(max_length=100, null=True, blank=True)
    href = models.TextField(null=True, blank=True)
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


def generate_unique_path(
    base_folder: str,
    name: str,
    team_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> str:
    desired = f"{base_folder}/{escape_path(name)}"
    path = desired
    index = 1

    # TODO: speed this up by making just one query, and zero on first insert
    # TODO: Check for team or project id existing
    while FileSystem.objects.filter(team_id=team_id, project_id=project_id, path=path).exists():
        path = f"{desired} ({index})"
        index += 1
    return path


def queryset_for_fs_data(fs_data: FileSystemRepresentation) -> QuerySet[FileSystem]:
    file_system_filters = {}
    if fs_data.team_id is not None:
        file_system_filters["team_id"] = fs_data.team_id
    if fs_data.project_id is not None:
        file_system_filters["project_id"] = fs_data.project_id
    return FileSystem.objects.filter(**file_system_filters, type=fs_data.type, ref=fs_data.ref)


def create_or_update_file(
    fs_data: FileSystemRepresentation,
    created_by: Optional[User] = None,
) -> FileSystem:
    existing = queryset_for_fs_data(fs_data).first()
    if existing:
        # Optionally rename the path to match the new name
        segments = split_path(existing.path)
        if len(segments) <= 2:
            new_path = generate_unique_path(
                fs_data.base_folder, fs_data.name, team_id=fs_data.team_id, project_id=fs_data.project_id
            )
        else:
            # Replace last segment
            segments[-1] = escape_path(fs_data.name)
            new_path = join_path(segments)

        # Ensure uniqueness
        # TODO: This previously only checked the path for that team - is that correct?
        if queryset_for_fs_data(fs_data).filter(path=new_path).exclude(id=existing.id).exists():
            new_path = generate_unique_path(
                fs_data.base_folder, fs_data.name, team_id=fs_data.team_id, project_id=fs_data.project_id
            )

        existing.path = new_path
        existing.depth = len(split_path(new_path))
        existing.href = fs_data.href
        existing.meta = fs_data.meta
        existing.save()
        return existing
    else:
        full_path = generate_unique_path(
            fs_data.base_folder, fs_data.name, team_id=fs_data.team_id, project_id=fs_data.project_id
        )
        new_fs = FileSystem.objects.create(
            team_id=fs_data.team_id,
            project_id=fs_data.project_id,
            path=full_path,
            depth=len(split_path(full_path)),
            type=fs_data.type,
            ref=fs_data.ref,
            href=fs_data.href,
            meta=fs_data.meta,
            created_by=created_by,
        )
        return new_fs


def delete_file(fs_data: FileSystemRepresentation):
    queryset_for_fs_data(fs_data).delete()


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
