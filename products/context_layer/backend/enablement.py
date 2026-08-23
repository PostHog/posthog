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
from products.context_layer.backend.scaffold import AGENTS_MD
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
    """Write every public channel under its project, importing CONTEXT.md when present.

    A channel is identified by the `channel_id` in its page's frontmatter, not
    by its slug: a channel that already has a page anywhere under `projects/`
    is never re-imported (later wiki edits win), and a new channel whose name
    collides with an existing page gets a suffixed slug instead of being
    silently dropped. Personal channels are skipped: their context belongs to
    one person, and the wiki is org-visible.
    """
    projects: list[tuple[int, str]] = []
    candidates: list[tuple[int, str, str, str | None]] = []
    # Order the teams so a same-named channel in two projects always resolves its
    # slug collision the same way; an unordered scan could swap the pages between runs.
    for team_id, team_name in (
        Team.objects.filter(organization_id=organization_id).order_by("id").values_list("id", "name")
    ):
        projects.append((team_id, team_name))
        # The enable request is org-scoped, so the fail-closed channel models
        # need an explicit team scope per team we read from.
        with team_scope(team_id):
            for channel in tasks_facade.list_channels(team_id, None):
                if channel.channel_type != "public":
                    continue
                instructions = tasks_facade.get_channel_instructions(channel.id, team_id, None)
                content = (
                    instructions.content
                    if instructions is not None and instructions.version > 0 and instructions.content.strip()
                    else None
                )
                candidates.append((team_id, str(channel.id), channel.name, content))

    if not projects:
        return []

    written: list[str] = []

    def mutate(root: Path) -> None:
        written.clear()
        agents_path = root / "AGENTS.md"
        if not agents_path.is_file() or agents_path.read_text(encoding="utf-8") != AGENTS_MD:
            agents_path.write_text(AGENTS_MD, encoding="utf-8")
            written.append("AGENTS.md")
        index = _existing_channel_pages(root)
        for team_id, team_name in projects:
            overview_path = f"projects/{team_id}/overview.md"
            if overview_path not in index.paths:
                target = root / overview_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_project_page(team_id, team_name), encoding="utf-8")
                index.paths.add(overview_path)
                written.append(overview_path)
        for team_id, channel_id, name, content in candidates:
            if channel_id in index.channel_ids:
                continue
            path = _unique_channel_path(team_id, name, channel_id, index.paths)
            index.paths.add(path)
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_channel_page(team_id, channel_id, name, content), encoding="utf-8")
            written.append(path)

    store.apply_changes(organization_id, message="Import channel context", mutate=mutate)
    return sorted(written)


@frozen
class ImportedChannelIndex:
    """Imported channel ids and paths already present in the wiki."""

    channel_ids: set[str]
    paths: set[str]


def _existing_channel_pages(root: Path) -> ImportedChannelIndex:
    channel_ids: set[str] = set()
    paths: set[str] = set()
    channels_dir = root / "projects"
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


def _unique_channel_path(team_id: int, name: str, channel_id: str, taken: set[str]) -> str:
    slug = slugify(name) or channel_id
    path = f"projects/{team_id}/spaces/{slug}.md"
    if path in taken:
        path = f"projects/{team_id}/spaces/{slug}-{channel_id[:8]}.md"
    return path


def _project_page(team_id: int, team_name: str) -> str:
    title = " ".join(team_name.split()) or f"Project {team_id}"
    return f"---\nproject_id: {team_id}\nproject_name: {title}\nsummary: Context for project {team_id}.\nstatus: active\nsources: project-catalog\n---\n\n# {title} (project {team_id})\n"


def _channel_page(team_id: int, channel_id: str, channel_name: str, content: str | None) -> str:
    title = " ".join(channel_name.split()) or channel_id
    if content is None:
        summary = f"Context for {title}."
        source = "channel-catalog"
        body = ""
    else:
        summary = f"Context imported from {title}."
        source = "channel-instructions-import"
        body = f"\n{content.strip()}\n"
    return f"---\nteam_id: {team_id}\nchannel_id: {channel_id}\nsummary: {summary}\nstatus: active\nsources: {source}\n---\n\n# {title} (project {team_id}, Space {channel_id[:8]})\n{body}"
