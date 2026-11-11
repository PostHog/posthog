from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models, transaction
from django.db.models import Func, OuterRef, Q, Subquery, TextField, Value
from django.db.models.expressions import F
from django.db.models.functions import Concat, Lower
from django.utils import timezone

from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7

SEARCH_TEXT = Lower(Concat(F("path"), Value(" "), F("type"), output_field=TextField()))
SEARCH_NAME = Lower(
    Func(F("path"), Value(r"^((?:[^\\/]|\\.)*/)*"), Value(""), function="regexp_replace", output_field=TextField())
)


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
    # Product surface this row belongs to (e.g. "web", "desktop"). NULL == DEFAULT_SURFACE.
    surface = models.CharField(max_length=100, null=True, blank=True)

    # DEPRECATED/UNUSED. It's all based on just the team_id.
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["team"]),
            models.Index(F("team_id"), F("surface"), F("path"), name="posthog_fs_team_s_path"),
            models.Index(F("team_id"), F("surface"), F("depth"), name="posthog_fs_team_s_depth"),
            models.Index(F("team_id"), F("surface"), F("type"), F("ref"), name="posthog_fs_team_s_typeref"),
            GinIndex(F("team_id"), OpClass(SEARCH_TEXT, name="gin_trgm_ops"), name="posthog_fs_team_text_trgm"),
            GinIndex(F("team_id"), OpClass(SEARCH_NAME, name="gin_trgm_ops"), name="posthog_fs_team_name_trgm"),
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
    surface: str = DEFAULT_SURFACE,
    create_parent_folders: bool = False,
):
    has_existing = False
    all_existing = (
        FileSystem.objects.filter(surface_q(surface), team=team, type=file_type, ref=ref)
        .filter(~Q(shortcut=True))
        .all()
    )
    for existing in all_existing:
        has_existing = True
        segments = split_path(existing.path)
        segments[-1] = name
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
            FileSystemShortcut.objects.filter(surface_q(surface), team=team, type=file_type, ref=ref)
            .filter(~(Q(path=path) & Q(href=href)))
            .all()
        )
        for shortcut in shortcuts:
            shortcut.path = path
            shortcut.href = href
            shortcut.save()
    else:
        full_path = f"{base_folder}/{escape_path(name)}"
        if create_parent_folders:
            assure_parent_folders(team, full_path, created_by_id, surface)
        FileSystem.objects.create(
            team=team,
            path=full_path,
            depth=len(split_path(full_path)),
            type=file_type,
            ref=ref,
            href=href,
            meta=meta,
            shortcut=False,
            surface=surface,
            created_by_id=created_by_id,
            created_at=created_at or timezone.now(),
        )


@dataclass(frozen=True)
class FolderMove:
    before: Optional[str]
    after: str
    path: str


def move_file_to_folder(
    *,
    team: Team,
    file_type: str,
    ref: str,
    folder: str,
    created_by_id: Optional[int] = None,
    surface: str = DEFAULT_SURFACE,
) -> Optional[FolderMove]:
    """Re-parent an item's entries under `folder`, keeping each entry's own name. None when it has no entry.

    An item can hold more than one non-shortcut entry (the default surface matches both NULL and "web" rows),
    so every one moves; otherwise the tree would show the item in two folders.
    """
    existing_files = list(
        FileSystem.objects.filter(surface_q(surface), team=team, type=file_type, ref=ref)
        .exclude(shortcut=True)
        .order_by("id")
    )
    if not existing_files:
        return None
    before = folder_of(existing_files[0].path)
    folder_segments = split_path(folder)
    with transaction.atomic():
        for index, existing in enumerate(existing_files):
            segments = [*folder_segments, split_path(existing.path)[-1]]
            if index == 0:
                assure_parent_folders(team, join_path(segments), created_by_id, surface)
            existing.path = join_path(segments)
            existing.depth = len(segments)
            existing.save()
    return FolderMove(before=before, after=folder, path=existing_files[0].path)


def assure_parent_folders(team: Team, path: str, created_by_id: Optional[int], surface: str = DEFAULT_SURFACE):
    """Create a folder entry for every ancestor of `path` that the project does not have yet."""
    segments = split_path(path)
    for depth in range(1, len(segments)):
        parent_path = join_path(segments[:depth])
        if not FileSystem.objects.filter(
            surface_q(surface), team__project_id=team.project_id, path=parent_path
        ).exists():
            FileSystem.objects.create(
                team=team,
                path=parent_path,
                depth=depth,
                type="folder",
                created_by_id=created_by_id,
                surface=surface,
            )


def folder_of(path: Optional[str]) -> Optional[str]:
    """The folder part of an entry path: everything above the item's own name."""
    return join_path(split_path(path)[:-1]) if path else None


def file_system_path_subquery(file_type: str, ref: Any) -> Subquery:
    """Path of an item's oldest default-surface entry, for annotating `_folder_path` on a list queryset."""
    entries = (
        FileSystem.objects.filter(surface_q(DEFAULT_SURFACE), team_id=OuterRef("team_id"), type=file_type, ref=ref)
        .exclude(shortcut=True)
        .order_by("id")
    )
    return Subquery(entries.values("path")[:1], output_field=TextField())


def delete_file(*, team: Team, file_type: str, ref: str, surface: str = DEFAULT_SURFACE):
    count, _ = FileSystem.objects.filter(surface_q(surface), team=team, type=file_type, ref=ref).delete()
    if count > 0:
        FileSystemShortcut.objects.filter(surface_q(surface), team=team, type=file_type, ref=ref).delete()


def delete_files(*, team: Team, file_type: str, refs: Sequence[str], surface: str = DEFAULT_SURFACE) -> None:
    count, _ = FileSystem.objects.filter(surface_q(surface), team=team, type=file_type, ref__in=refs).delete()
    if count > 0:
        FileSystemShortcut.objects.filter(surface_q(surface), team=team, type=file_type, ref__in=refs).delete()


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
