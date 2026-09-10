"""Migrate the desktop file-system tree into first-class channels and canvases.

The desktop "file system" conflated four things that now have real homes:

- top-level folders → tasks ``Channel`` rows (resolve-or-create by the same
  normalized name the old client bridge used; a folder named "me" maps to its
  creator's personal channel);
- ``dashboard`` rows → ``Canvas`` rows, preserving the row UUID so canvas
  deep links and loop references keep working (``meta.code`` is carried in
  ``legacy_code`` until the next publish creates a real source version);
- folder instructions / context-generation markers → their channel-scoped
  equivalents;
- shortcuts → ``ChannelStar`` rows, and ``task`` filings → a ``Task.channel``
  backfill. Physical cleanup is intentionally deferred to a later deployment.

Loop ``context_target`` payloads are rewritten from ``folder_id`` (a desktop
folder) to ``channel_id``.
"""

import re
import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from django.db import migrations

logger = logging.getLogger(__name__)


def _normalize_channel_name(name: str) -> str:
    # Mirrors products.tasks.backend.facade.api.normalize_channel_name.
    return re.sub(r"\s+", "-", str(name).strip().lower())[:128]


def _leaf(path: str) -> str:
    segments = [segment for segment in re.split(r"(?<!\\)/", path or "") if segment]
    return segments[-1].replace("\\/", "/") if segments else ""


def _parent_path(path: str) -> str:
    segments = re.split(r"(?<!\\)/", path or "")
    return "/".join(segments[:-1])


def _ms_to_datetime(value):
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def migrate_desktop_tree(apps, schema_editor):
    FileSystem = apps.get_model("posthog", "FileSystem")
    FileSystemShortcut = apps.get_model("posthog", "FileSystemShortcut")
    FolderInstructions = apps.get_model("posthog", "FileSystemFolderInstructions")
    FolderContextGeneration = apps.get_model("posthog", "FileSystemFolderContextGeneration")
    Channel = apps.get_model("tasks", "Channel")
    ChannelInstructions = apps.get_model("tasks", "ChannelInstructions")
    ChannelContextGeneration = apps.get_model("tasks", "ChannelContextGeneration")
    ChannelStar = apps.get_model("tasks", "ChannelStar")
    Task = apps.get_model("tasks", "Task")
    Loop = apps.get_model("tasks", "Loop")
    Canvas = apps.get_model("canvas", "Canvas")

    # One scan of the (large, team-indexed-only) file-system table, bucketed by
    # team up front instead of re-filtered per team.
    folders_by_team: dict[int, list] = defaultdict(list)
    dashboards_by_team: dict[int, list] = defaultdict(list)
    for row in FileSystem.objects.filter(surface="desktop", type__in=["folder", "dashboard"]).iterator(chunk_size=1000):
        (folders_by_team if row.type == "folder" else dashboards_by_team)[row.team_id].append(row)

    # Rows that don't fit the expected shape are skipped or emptied; count them
    # so an operator can see what the migration dropped before 1266 deletes the
    # source rows for good.
    counts: Counter[str] = Counter()

    for team_id in sorted(folders_by_team.keys() | dashboards_by_team.keys()):
        team_folders = folders_by_team.get(team_id, [])
        team_dashboards = dashboards_by_team.get(team_id, [])

        # 1. Top-level folders → channels. Deeper folders resolve through their
        # top-level ancestor; "Unfiled" is the tree's system folder, not a channel.
        channel_by_folder_id: dict[str, Any] = {}
        channel_by_top_path: dict[tuple[str, int | None], Any] = {}
        for folder in team_folders:
            top = re.split(r"(?<!\\)/", folder.path or "")[0]
            normalized = _normalize_channel_name(top.replace("\\/", "/"))
            if not normalized or normalized == "unfiled":
                continue
            if normalized == "me" and not folder.created_by_id:
                counts["personal_folder_skipped_no_owner"] += 1
                continue
            owner_key = folder.created_by_id if normalized == "me" else None
            cache_key = (normalized, owner_key)
            channel = channel_by_top_path.get(cache_key)
            if channel is None:
                if normalized == "me" and folder.created_by_id:
                    channel, _ = Channel.objects.get_or_create(
                        team_id=team_id,
                        created_by_id=folder.created_by_id,
                        channel_type="personal",
                        deleted=False,
                        defaults={"name": "me"},
                    )
                else:
                    channel, _ = Channel.objects.get_or_create(
                        team_id=team_id,
                        name=normalized,
                        channel_type="public",
                        deleted=False,
                        defaults={"created_by_id": folder.created_by_id},
                    )
                channel_by_top_path[cache_key] = channel
            channel_by_folder_id[str(folder.id)] = channel

        def channel_for_path(path: str, owner_id: int | None, _channels=channel_by_top_path):
            top = re.split(r"(?<!\\)/", path or "")[0]
            normalized = _normalize_channel_name(top.replace("\\/", "/"))
            return _channels.get((normalized, owner_id if normalized == "me" else None))

        # 2. Dashboard rows → Canvas rows (UUIDs preserved).
        home_canvas_ids: set[str] = set()
        for folder in team_folders:
            home_id = (folder.meta or {}).get("homeCanvasId")
            if home_id:
                home_canvas_ids.add(str(home_id))

        # is_home is unique per channel: two folders resolving to the same
        # channel can both carry homeCanvasId, so only the first one wins —
        # otherwise the second insert violates unique_home_canvas_per_channel
        # and aborts the whole migration.
        home_assigned: set = set()
        for row in team_dashboards:
            meta = row.meta or {}
            channel = channel_by_folder_id.get(str(meta.get("channelId") or "")) or channel_for_path(
                row.path, row.created_by_id
            )
            if channel is None:
                counts["dashboard_skipped_no_channel"] += 1
                continue
            is_home = str(row.id) in home_canvas_ids and channel.id not in home_assigned
            if is_home:
                home_assigned.add(channel.id)
            code = meta.get("code")
            Canvas.objects.get_or_create(
                id=row.id,
                defaults={
                    "team_id": team_id,
                    "channel_id": channel.id,
                    "name": _leaf(row.path) or "Canvas",
                    "template_id": str(meta.get("templateId") or "freeform"),
                    "context": meta.get("context") if isinstance(meta.get("context"), str) else "",
                    "generation_task_id": meta.get("generationTaskId") or None,
                    "pinned_at": _ms_to_datetime(meta.get("pinnedAt")),
                    "is_home": is_home,
                    "legacy_code": code if isinstance(code, str) and code.strip() else None,
                    "created_by_id": row.created_by_id,
                    "created_at": _ms_to_datetime(meta.get("createdAt")) or row.created_at,
                },
            )

        # 3. Folder instructions → channel instructions (history preserved).
        folder_ids = [row.id for row in team_folders]
        migrated_channel_versions: dict[Any, int] = {}
        for instruction in FolderInstructions.objects.filter(folder_id__in=folder_ids).order_by(
            "version", "created_at"
        ):
            channel = channel_by_folder_id.get(str(instruction.folder_id))
            if channel is None:
                continue
            migrated_version = migrated_channel_versions.get(channel.id, 0) + 1
            migrated_channel_versions[channel.id] = migrated_version
            ChannelInstructions.objects.create(
                channel_id=channel.id,
                version=migrated_version,
                team_id=team_id,
                content=instruction.content,
                is_latest=False,
                deleted=instruction.deleted,
                created_by_id=instruction.created_by_id,
                created_at=instruction.created_at,
            )
        for channel_id, latest_version in migrated_channel_versions.items():
            ChannelInstructions.objects.filter(channel_id=channel_id, version=latest_version).update(is_latest=True)
        for marker in FolderContextGeneration.objects.filter(folder_id__in=folder_ids):
            channel = channel_by_folder_id.get(str(marker.folder_id))
            if channel is None or not marker.task_id:
                counts["context_marker_skipped"] += 1
                continue
            ChannelContextGeneration.objects.get_or_create(
                channel_id=channel.id, defaults={"team_id": team_id, "task_id": marker.task_id}
            )

        # 4. Shortcuts (stars) → ChannelStar. Desktop shortcuts point at channel
        # folders by path (`ref`).
        for shortcut in FileSystemShortcut.objects.filter(team_id=team_id, surface="desktop"):
            channel = channel_for_path(shortcut.ref or shortcut.path or "", shortcut.user_id)
            if channel is None or not shortcut.user_id:
                counts["star_skipped_no_channel"] += 1
                continue
            ChannelStar.objects.get_or_create(
                channel_id=channel.id, user_id=shortcut.user_id, defaults={"team_id": team_id}
            )

        # 5. Task filings → Task.channel backfill (filings outside Unfiled/ name
        # the channel the task was filed into).
        for filing in FileSystem.objects.filter(team_id=team_id, surface="desktop", type="task").exclude(
            path__startswith="Unfiled/"
        ):
            if not filing.ref:
                continue
            channel = channel_for_path(filing.path, filing.created_by_id)
            if channel is None:
                counts["task_filing_skipped_no_channel"] += 1
                continue
            Task.objects.filter(team_id=team_id, id=filing.ref, channel__isnull=True).update(channel_id=channel.id)

        # 6. Loop context targets: folder_id → channel_id.
        for loop in Loop.objects.filter(team_id=team_id).exclude(context_target={}):
            target = loop.context_target or {}
            folder_id = target.get("folder_id")
            if not folder_id:
                continue
            channel = channel_by_folder_id.get(str(folder_id))
            if channel is None and target.get("name"):
                normalized = _normalize_channel_name(target["name"])
                channel = Channel.objects.filter(
                    team_id=team_id, name=normalized, channel_type="public", deleted=False
                ).first()
            target.pop("folder_id", None)
            if channel is not None:
                target["channel_id"] = str(channel.id)
                loop.context_target = target
            else:
                # The folder didn't resolve to a channel; the target is dropped
                # but the loop survives.
                loop.context_target = {}
                counts["loop_target_emptied"] += 1
            loop.save(update_fields=["context_target"])

    if counts:
        # These rows have no other home after the desktop surface is dropped —
        # surface what was dropped so it can be reviewed before that runs.
        logger.warning("desktop_tree_migration_dropped: %s", dict(counts))


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0002_source_version_required"),
        ("tasks", "0081_channelcontextgeneration_channelinstructions_and_more"),
        ("posthog", "1265_delete_duckgresserverteam"),
    ]

    operations = [
        migrations.RunPython(migrate_desktop_tree, migrations.RunPython.noop, elidable=False),
    ]
