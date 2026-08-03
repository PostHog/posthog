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
  backfill.

Loop ``context_target`` payloads are rewritten from ``folder_id`` (a desktop
folder) to ``channel_id``. One-way: the desktop tree is deleted by the
follow-up posthog migration.
"""

import re
from datetime import UTC, datetime

from django.db import migrations


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

    folders = list(FileSystem.objects.filter(surface="desktop", type="folder"))
    dashboards = list(FileSystem.objects.filter(surface="desktop", type="dashboard"))
    team_ids = {row.team_id for row in folders} | {row.team_id for row in dashboards}

    for team_id in sorted(team_ids):
        team_folders = [row for row in folders if row.team_id == team_id]
        team_dashboards = [row for row in dashboards if row.team_id == team_id]

        # 1. Top-level folders → channels. Deeper folders resolve through their
        # top-level ancestor; "Unfiled" is the tree's system folder, not a channel.
        channel_by_folder_id: dict[str, object] = {}
        channel_by_top_path: dict[str, object] = {}
        for folder in team_folders:
            top = re.split(r"(?<!\\)/", folder.path or "")[0]
            normalized = _normalize_channel_name(top.replace("\\/", "/"))
            if not normalized or normalized == "unfiled":
                continue
            channel = channel_by_top_path.get(top)
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
                channel_by_top_path[top] = channel
            channel_by_folder_id[str(folder.id)] = channel

        def channel_for_path(path: str, _channels=channel_by_top_path):
            top = re.split(r"(?<!\\)/", path or "")[0]
            return _channels.get(top)

        # 2. Dashboard rows → Canvas rows (UUIDs preserved).
        home_canvas_ids: set[str] = set()
        for folder in team_folders:
            home_id = (folder.meta or {}).get("homeCanvasId")
            if home_id:
                home_canvas_ids.add(str(home_id))

        for row in team_dashboards:
            meta = row.meta or {}
            channel = channel_by_folder_id.get(str(meta.get("channelId") or "")) or channel_for_path(row.path)
            if channel is None:
                continue
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
                    "is_home": str(row.id) in home_canvas_ids,
                    "legacy_code": code if isinstance(code, str) and code.strip() else None,
                    "created_by_id": row.created_by_id,
                    "created_at": _ms_to_datetime(meta.get("createdAt")) or row.created_at,
                },
            )

        # 3. Folder instructions → channel instructions (history preserved).
        folder_ids = [row.id for row in team_folders]
        migrated_channels: set = set()
        for instruction in FolderInstructions.objects.filter(folder_id__in=folder_ids).order_by(
            "version", "created_at"
        ):
            channel = channel_by_folder_id.get(str(instruction.folder_id))
            if channel is None:
                continue
            key = (channel.id, instruction.version)
            if key in migrated_channels:
                continue
            migrated_channels.add(key)
            ChannelInstructions.objects.get_or_create(
                channel_id=channel.id,
                version=instruction.version,
                defaults={
                    "team_id": team_id,
                    "content": instruction.content,
                    "is_latest": instruction.is_latest,
                    "deleted": instruction.deleted,
                    "created_by_id": instruction.created_by_id,
                    "created_at": instruction.created_at,
                },
            )
        for marker in FolderContextGeneration.objects.filter(folder_id__in=folder_ids):
            channel = channel_by_folder_id.get(str(marker.folder_id))
            if channel is None or not marker.task_id:
                continue
            ChannelContextGeneration.objects.get_or_create(
                channel_id=channel.id, defaults={"team_id": team_id, "task_id": marker.task_id}
            )

        # 4. Shortcuts (stars) → ChannelStar. Desktop shortcuts point at channel
        # folders by path (`ref`).
        for shortcut in FileSystemShortcut.objects.filter(team_id=team_id, surface="desktop"):
            channel = channel_for_path(shortcut.ref or shortcut.path or "")
            if channel is None or not shortcut.user_id:
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
            channel = channel_for_path(filing.path)
            if channel is None:
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
                loop.context_target = {}
            loop.save(update_fields=["context_target"])


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0001_initial"),
        ("tasks", "0076_channelcontextgeneration_channelinstructions_and_more"),
        ("posthog", "1265_delete_duckgresserverteam"),
    ]

    operations = [
        migrations.RunPython(migrate_desktop_tree, migrations.RunPython.noop, elidable=False),
    ]
