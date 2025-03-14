from django.db import models
from typing import Optional

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


class FileSystem(models.Model):
    """
    A generic "file system" model that can represent hierarchical
    folders and "files" for any object type in PostHog.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid7)

    path = models.TextField()
    depth = models.IntegerField(null=True, blank=True)
    type = models.CharField(max_length=100, blank=True)
    ref = models.CharField(max_length=100, null=True, blank=True)
    href = models.TextField(null=True, blank=True)
    meta = models.JSONField(default=dict, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.path


def generate_unique_path(team: Team, base_folder: str, name: str) -> str:
    desired = f"{base_folder}/{escape_path(name)}"
    path = desired
    index = 1
    while FileSystem.objects.filter(team=team, path=path).exists():
        path = f"{desired} ({index})"
        index += 1
    return path


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
) -> FileSystem:
    existing = FileSystem.objects.filter(team=team, type=file_type, ref=ref).first()
    if existing:
        # Optionally, update path to match the new name – or leave as-is if you don't want to rename once created.
        segments = split_path(existing.path)
        # Example: if we want to keep the same base folder and rename only the last segment:
        if len(segments) <= 2:
            # Just generate a brand-new path if there's no "folder" portion
            new_path = generate_unique_path(team, base_folder, name)
        else:
            # Replace last segment with new name, ensuring uniqueness
            # This approach might cause collisions, so if you want bulletproof uniqueness,
            # you can rely on generate_unique_path again. For brevity here, we do a direct swap.
            segments[-1] = escape_path(name)
            new_path = "/".join(segments)

        # Ensure uniqueness in any case
        if FileSystem.objects.filter(team=team, path=new_path).exclude(id=existing.id).exists():
            new_path = generate_unique_path(team, base_folder, name)

        existing.path = new_path
        existing.depth = len(split_path(new_path))
        existing.href = href
        existing.meta = meta
        existing.save()
        return existing
    else:
        full_path = generate_unique_path(team, base_folder, name)
        new_fs = FileSystem.objects.create(
            team=team,
            path=full_path,
            depth=len(split_path(full_path)),
            type=file_type,
            ref=ref,
            href=href,
            meta=meta,
            created_by=created_by,
        )
        return new_fs


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
