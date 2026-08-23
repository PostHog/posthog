"""Enable the context layer for an organization: scaffold the wiki, then import
existing channel CONTEXT.md documents once.

The legacy ChannelInstructions rows are never deleted, so turning the flag off
restores the old behavior exactly as it was at import time.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.utils.text import slugify

import structlog

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.context_layer.backend import store
from products.context_layer.backend.models import ContextLayerConfig
from products.tasks.backend.facade import api as tasks_facade

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
    if Team.objects.filter(organization_id=organization_id, access_control=True).exists():
        raise RestrictedProjectsError(
            "This organization has private projects. The context layer does not support them yet."
        )
    config = store.initialize_repo(organization_id, created_by_id=created_by_id)
    import_channel_context(organization_id)
    return config


def import_channel_context(organization_id: uuid.UUID | str) -> list[str]:
    """Write each public channel's latest CONTEXT.md as `channels/<slug>.md`.

    Pages that already exist are left alone, so the import runs once per channel
    and never overwrites later wiki edits. Personal channels are skipped: their
    context belongs to one person, and the wiki is org-visible.
    """
    imported: dict[str, str] = {}
    existing_slugs: set[str] = set()
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
                slug = _unique_slug(channel.name, channel.id, existing_slugs)
                existing_slugs.add(slug)
                imported[f"channels/{slug}.md"] = _channel_page(channel.id, channel.name, instructions.content)

    if not imported:
        return []

    written: list[str] = []

    def mutate(root: Path) -> None:
        written.clear()
        for path, content in imported.items():
            target = root / path
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(path)

    store.apply_changes(organization_id, message="Import channel context", mutate=mutate)
    return sorted(written)


def _unique_slug(name: str, channel_id: uuid.UUID, taken: set[str]) -> str:
    slug = slugify(name) or str(channel_id)
    if slug in taken:
        # Channel names are only unique per team, so cross-team collisions get
        # the channel id appended.
        slug = f"{slug}-{str(channel_id)[:8]}"
    return slug


def _channel_page(channel_id: uuid.UUID, channel_name: str, content: str) -> str:
    return f"---\nchannel_id: {channel_id}\nsource: channel-instructions-import\n---\n\n# {channel_name}\n\n{content}\n"
