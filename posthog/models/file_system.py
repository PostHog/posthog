from django.db import models
from typing import Optional

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


def split_path(path: str) -> list[str]:
    r"""
    Split a path on unescaped '/' delimiters.
    Example:
        "Unfiled/Feature Flags/Flag A" -> ["Unfiled", "Feature Flags", "Flag A"]
        Handles escaping, so "My\/Path" is split as ["My/Path"].
    """
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
    """
    Escape path segments by:
    - replacing '\' with '\\'
    - replacing '/' with '\\/'
    """
    path = path.replace("\\", "\\\\")
    path = path.replace("/", "\\/")
    return path


def join_path(segments: list[str]) -> str:
    """
    Join escaped path segments with '/' delimiter.
    """
    return "/".join(escape_path(segment) for segment in segments)


class FileSystem(models.Model):
    """
    A generic "file system" model that can represent hierarchical
    folders and "files" for any object type in PostHog.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid7)

    # Full path, e.g. "Unfiled/Feature Flags/My Flag"
    path = models.TextField()

    # Depth is just for convenience (0 = root, 1 = 'Unfiled', etc.)
    depth = models.IntegerField(null=True, blank=True)

    # 'type' might be "feature_flag", "experiment", "dashboard", etc.
    type = models.CharField(max_length=100, blank=True)

    # 'ref' is the unique string reference for the associated object,
    # typically the object's ID or short_id. This is how we link the
    # FileSystem entry back to the domain object.
    ref = models.CharField(max_length=100, null=True, blank=True)

    # A pointer to the UI route for the object (e.g. "/feature_flags/123")
    href = models.TextField(null=True, blank=True)

    # Arbitrary metadata (timestamps, creator info, etc.)
    meta = models.JSONField(default=dict, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.path


def generate_unique_path(team: Team, base_folder: str, name: str) -> str:
    """
    Given a base folder (e.g. 'Unfiled/Feature Flags') and an item name,
    generate a path that does not yet exist for this team in `FileSystem`.

    If there's a collision, appends a numeric suffix: e.g. "... (1)", "... (2)", etc.
    """
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
    """
    Create or update the `FileSystem` entry for a given domain object.
      - If a FileSystem entry (team + file_type + ref) already exists, we update it.
      - Otherwise we create a new entry with a unique path under `base_folder`.
    """
    existing = FileSystem.objects.filter(team=team, type=file_type, ref=ref).first()
    if existing:
        # Update existing entry's name in path, if desired.
        segments = split_path(existing.path)

        # The first segments might be ["Unfiled", "Feature Flags"] => keep them,
        # rename only the last segment
        if len(segments) > 0:
            # base_folder might have changed, but let's assume it's the same.
            # We'll do a new base_folder + name approach.
            new_full_path = (
                generate_unique_path(team, base_folder, name)
                if len(segments) <= 2
                else join_path(segments[:-1]) + "/" + escape_path(name)
            )
            existing.path = new_full_path
            existing.depth = len(split_path(new_full_path))

        existing.href = href
        existing.meta = meta
        existing.save()
        return existing
    else:
        # Create new entry
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
    """
    Deletes the FileSystem entry corresponding to (team, file_type, ref) if it exists.
    """
    FileSystem.objects.filter(team=team, type=file_type, ref=ref).delete()
