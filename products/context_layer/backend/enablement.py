"""Enable the context layer for an organization: scaffold the wiki, then import
existing channel CONTEXT.md documents once.

The legacy ChannelInstructions rows are never deleted, so turning the flag off
restores the old behavior exactly as it was at import time.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.db import transaction
from django.utils.text import slugify

import structlog

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.context_layer.backend import store
from products.context_layer.backend.models import ContextLayerConfig
from products.tasks.backend.facade import api as tasks_facade

from ee.models.rbac.access_control import AccessControl

logger = structlog.get_logger(__name__)


class RestrictedProjectsError(store.ContextLayerStoreError):
    """The organization has private projects; enabling waits for per-project partitioning."""


def enable_context_layer(
    organization_id: uuid.UUID | str,
    *,
    created_by_id: int | None = None,
) -> ContextLayerConfig:
    """Idempotent: re-enabling scaffolds nothing and re-imports only missing pages."""
    # Context extracted with one project's credentials must not become readable
    # through another, so orgs with private projects cannot enable until the
    # wiki is partitioned per project.
    private_names = private_project_names(organization_id)
    if private_names:
        joined = ", ".join(private_names)
        raise RestrictedProjectsError(
            f"This organization has private projects ({joined}). The context layer does not "
            "support them yet. Remove those projects' access restrictions to enable it."
        )
    config = store.initialize_repo(organization_id, created_by_id=created_by_id)
    import_channel_context(organization_id)
    # The import lands its own commit, so the row read before it is already a
    # head behind. Callers use this sha as `base_head`, and a stale one costs
    # them a spurious conflict on their first write.
    config.refresh_from_db()
    transaction.on_commit(lambda: _trigger_bootstrap_dream(str(organization_id)), robust=True)
    return config


def _trigger_bootstrap_dream(organization_id: str) -> None:
    from products.context_layer.backend.temporal.dreaming import (  # noqa: PLC0415, I001 — keeps Temporal off Django's enablement import path
        trigger_bootstrap_dream,
    )

    trigger_bootstrap_dream(organization_id)


def organization_has_private_projects(organization_id: uuid.UUID | str) -> bool:
    """Private projects exist in two representations: the deprecated
    `Team.access_control` flag (orgs not yet RBAC-migrated) and a project-level
    `AccessControl` row with `access_level="none"`. Enablement must respect
    both, and cares about the row existing rather than whether access control
    is currently entitled, so it does not gate on the feature."""
    if Team.objects.filter(organization_id=organization_id, access_control=True).exists():
        return True
    # Any project-level "none" row counts — the org-wide default row
    # (organization_member/role null) marks a private project, and a member- or
    # role-specific denial means at least one person must not see that
    # project's context either way.
    return AccessControl.objects.filter(
        team__organization_id=organization_id,
        resource="project",
        resource_id__isnull=False,
        access_level="none",
    ).exists()


def private_project_names(organization_id: uuid.UUID | str) -> list[str]:
    """Names of the projects blocking enablement, for the error an org admin
    acts on. Same two representations as `organization_has_private_projects`."""
    names = set(
        Team.objects.filter(organization_id=organization_id, access_control=True).values_list("name", flat=True)
    )
    restricted_ids = AccessControl.objects.filter(
        team__organization_id=organization_id,
        resource="project",
        resource_id__isnull=False,
        access_level="none",
    ).values_list("resource_id", flat=True)
    names.update(
        Team.objects.filter(organization_id=organization_id, id__in=list(restricted_ids)).values_list("name", flat=True)
    )
    return sorted(names)


def import_channel_context(organization_id: uuid.UUID | str) -> list[str]:
    """Write each public channel's latest CONTEXT.md as `channels/<slug>.md`.

    A channel is identified by the `channel_id` in its page's frontmatter, not
    by its slug: a channel that already has a page anywhere under `channels/`
    is never re-imported (later wiki edits win), and a new channel whose name
    collides with an existing page gets a suffixed slug instead of being
    silently dropped. Personal channels are skipped: their context belongs to
    one person, and the wiki is org-visible.
    """
    candidates: list[tuple[str, str, str]] = []
    # Order the teams so a same-named channel in two projects always resolves its
    # slug collision the same way; an unordered scan could swap the pages between runs.
    for team_id in Team.objects.filter(organization_id=organization_id).order_by("id").values_list("id", flat=True):
        # The enable request is org-scoped, so the fail-closed channel models
        # need an explicit team scope per team we read from.
        with team_scope(team_id):
            for channel in tasks_facade.list_channels(team_id, None):
                if channel.channel_type != "public":
                    continue
                instructions = tasks_facade.get_channel_instructions(channel.id, team_id, None)
                if instructions is None or instructions.version == 0 or not instructions.content.strip():
                    continue
                candidates.append((str(channel.id), channel.name, instructions.content))

    if not candidates:
        return []

    written: list[str] = []

    def mutate(root: Path) -> None:
        written.clear()
        index = _existing_channel_pages(root)
        for channel_id, name, content in candidates:
            if channel_id in index.channel_ids:
                continue
            path = _unique_channel_path(name, channel_id, index.paths)
            index.paths.add(path)
            # The linter requires H1 titles to be unique wiki-wide, so a page
            # that needed a disambiguated path needs a disambiguated title too.
            title = name if path == f"channels/{slugify(name) or channel_id}.md" else f"{name} ({channel_id[:8]})"
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_channel_page(channel_id, name, content, title=title), encoding="utf-8")
            written.append(path)

    store.apply_changes(organization_id, message="Import channel context", mutate=mutate)
    return sorted(written)


@frozen
class ImportedChannelIndex:
    """What already lives under channels/: imported channel ids and taken paths."""

    channel_ids: set[str]
    paths: set[str]


def _existing_channel_pages(root: Path) -> ImportedChannelIndex:
    channel_ids: set[str] = set()
    paths: set[str] = set()
    channels_dir = root / "channels"
    if channels_dir.is_dir():
        for page in channels_dir.rglob("*.md"):
            paths.add(str(page.relative_to(root)))
            channel_id = _frontmatter_value(page, "channel_id")
            if channel_id:
                channel_ids.add(channel_id)
    return ImportedChannelIndex(channel_ids=channel_ids, paths=paths)


def _frontmatter_value(page: Path, key: str) -> str | None:
    lines = page.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip() or None
    return None


def _unique_channel_path(name: str, channel_id: str, taken: set[str]) -> str:
    slug = slugify(name) or channel_id
    path = f"channels/{slug}.md"
    if path in taken:
        # Channel names are only unique per team, so cross-team collisions get
        # the channel id appended.
        path = f"channels/{slug}-{channel_id[:8]}.md"
    return path


def _channel_page(channel_id: str, channel_name: str, content: str, *, title: str | None = None) -> str:
    return f"---\nchannel_id: {channel_id}\nsummary: Context imported from {channel_name}.\nstatus: active\nsources: channel-instructions-import\n---\n\n# {title or channel_name}\n\n{content}\n"
