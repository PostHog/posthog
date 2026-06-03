"""`manage.py seed_canonical_templates` — load `@posthog/*` registry rows.

Reads markdown files vendored under `products/agent_platform/backend/canonical_templates/`
and upserts an `AgentSkillTemplate` row per file (team_id=NULL — canonical).
Existing canonical rows with the same `(name, version)` get updated in place;
new versions only land when the file's frontmatter explicitly bumps `version`.

Layout convention:

    canonical_templates/
        skills/
            research.md          → name=@posthog/research, body=file content
            posthog-mcp.md       → name=@posthog/posthog-mcp, body=file content
            <slug>/SKILL.md      → name=@posthog/<slug>
            <slug>/<file>.md     → companion files attached to that template

Each markdown file is a spec-compliant `SKILL.md` — a YAML frontmatter
block (between `---` lines) with the Agent Skills fields (`name`,
`description`, `license`, `compatibility`, `metadata`, `allowed-tools`)
followed by the body. The registry-row version comes from
`metadata.version` (falling back to a top-level `version` for legacy
fixtures); defaults to 1. `name`, when present, must match the file's
slug.

Idempotent — re-running on an unchanged directory is a no-op. Designed to
be safe in `bin/run_smoke_tests.sh` and prod seed pipelines.

Run locally:

    python manage.py seed_canonical_templates
    python manage.py seed_canonical_templates --dry-run
    python manage.py seed_canonical_templates --path /custom/path
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import yaml

from products.agent_platform.backend.models import AgentSkillTemplate, AgentSkillTemplateFile
from products.agent_platform.backend.skill_frontmatter import SkillSpecError, validate_skill_spec

# Vendored alongside this command so the seed is reproducible from a fresh checkout.
DEFAULT_SOURCE_DIR = Path(__file__).resolve().parent.parent.parent / "canonical_templates"


class Command(BaseCommand):
    help = "Seed the canonical `@posthog/*` skill template rows from vendored markdown."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--path",
            type=str,
            default=str(DEFAULT_SOURCE_DIR),
            help="Override the source directory. Defaults to the vendored `canonical_templates/`.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List intended changes without writing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_dir = Path(options["path"])
        dry_run = options["dry_run"]

        if not source_dir.exists():
            self.stdout.write(self.style.WARNING(f"Source dir {source_dir} does not exist — nothing to seed."))
            return

        skills_dir = source_dir / "skills"
        entries = list(_iter_canonical_skills(skills_dir)) if skills_dir.exists() else []
        if not entries:
            self.stdout.write(self.style.WARNING(f"No canonical skill markdown found in {skills_dir}."))
            return

        with transaction.atomic():
            created, updated, unchanged = 0, 0, 0
            for entry in entries:
                action = self._upsert_skill(entry, dry_run=dry_run)
                if action == "created":
                    created += 1
                elif action == "updated":
                    updated += 1
                else:
                    unchanged += 1
            if dry_run:
                # Roll back so a dry run never leaves partial state behind.
                transaction.set_rollback(True)

        verb = "Would" if dry_run else "Did"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} create {created}, update {updated}, leave {unchanged} unchanged "
                f"(total {len(entries)} canonical skills)."
            )
        )

    def _upsert_skill(self, entry: _CanonicalSkill, *, dry_run: bool) -> str:
        canonical_name = f"@posthog/{entry.slug}"
        existing = AgentSkillTemplate.objects.filter(
            team__isnull=True, name=canonical_name, version=entry.version, deleted=False
        ).first()
        if existing:
            same_body = existing.body == entry.body
            same_desc = existing.description == entry.description
            same_meta = (
                existing.license == entry.license
                and existing.compatibility == entry.compatibility
                and existing.metadata == entry.metadata
                and list(existing.allowed_tools) == entry.allowed_tools
            )
            existing_files = {f.path: f.content for f in existing.files.all()}
            new_files = {f.path: f.content for f in entry.files}
            same_files = existing_files == new_files
            if same_body and same_desc and same_meta and same_files:
                return "unchanged"
            if not dry_run:
                existing.body = entry.body
                existing.description = entry.description
                existing.license = entry.license
                existing.compatibility = entry.compatibility
                existing.metadata = entry.metadata
                existing.allowed_tools = entry.allowed_tools
                existing.save(
                    update_fields=[
                        "body",
                        "description",
                        "license",
                        "compatibility",
                        "metadata",
                        "allowed_tools",
                        "updated_at",
                    ]
                )
                # Replace companion files. Canonical templates are small —
                # full replace is simpler than diff-by-diff.
                existing.files.all().delete()
                for f in entry.files:
                    AgentSkillTemplateFile.objects.create(
                        template=existing,
                        path=f.path,
                        content=f.content,
                    )
            return "updated"

        if dry_run:
            return "created"

        # Flip any other latest row for this name so the new version becomes is_latest.
        AgentSkillTemplate.objects.filter(team__isnull=True, name=canonical_name, deleted=False).update(is_latest=False)
        template = AgentSkillTemplate.objects.create(
            team=None,
            name=canonical_name,
            description=entry.description,
            body=entry.body,
            license=entry.license,
            compatibility=entry.compatibility,
            metadata=entry.metadata,
            allowed_tools=entry.allowed_tools,
            version=entry.version,
            is_latest=True,
        )
        for f in entry.files:
            AgentSkillTemplateFile.objects.create(template=template, path=f.path, content=f.content)
        return "created"


# ── parsing ────────────────────────────────────────────────────────────────


class _CanonicalFile:
    """Companion file alongside a SKILL.md."""

    __slots__ = ("path", "content")

    def __init__(self, path: str, content: str) -> None:
        self.path = path
        self.content = content


class _CanonicalSkill:
    __slots__ = (
        "slug",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed_tools",
        "version",
        "body",
        "files",
    )

    def __init__(
        self,
        slug: str,
        description: str,
        license: str,
        compatibility: str,
        metadata: dict[str, str],
        allowed_tools: list[str],
        version: int,
        body: str,
        files: list[_CanonicalFile],
    ) -> None:
        self.slug = slug
        self.description = description
        self.license = license
        self.compatibility = compatibility
        self.metadata = metadata
        self.allowed_tools = allowed_tools
        self.version = version
        self.body = body
        self.files = files


def _iter_canonical_skills(skills_dir: Path) -> list[_CanonicalSkill]:
    """Walk `skills_dir` and yield one `_CanonicalSkill` per leaf.

    Supports two layouts in the same directory:
      - `skills/<slug>.md` — single-file skill, body only
      - `skills/<slug>/SKILL.md` — multi-file skill, plus other `.md` companions
    """
    out: list[_CanonicalSkill] = []
    for entry in sorted(skills_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".md":
            out.append(_build_skill(entry.stem, entry.read_text(), []))
        elif entry.is_dir():
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            companions: list[_CanonicalFile] = []
            for child in sorted(entry.rglob("*")):
                if child == skill_md or not child.is_file():
                    continue
                rel = child.relative_to(entry).as_posix()
                companions.append(_CanonicalFile(rel, child.read_text()))
            out.append(_build_skill(entry.name, skill_md.read_text(), companions))
    return out


def _build_skill(slug: str, text: str, files: list[_CanonicalFile]) -> _CanonicalSkill:
    """Parse a spec-compliant SKILL.md into a `_CanonicalSkill`, validating it."""
    meta, body = _parse_frontmatter(text)

    name = meta.get("name")
    if name is not None and str(name) != slug:
        raise CommandError(f"canonical skill {slug!r}: frontmatter name {name!r} must match the file slug.")

    description = str(meta.get("description", ""))
    license = str(meta.get("license", ""))
    compatibility = str(meta.get("compatibility", ""))

    raw_metadata = meta.get("metadata") or {}
    metadata = {str(k): str(v) for k, v in raw_metadata.items()} if isinstance(raw_metadata, dict) else {}
    allowed_tools = _parse_allowed_tools(meta.get("allowed-tools", meta.get("allowed_tools")))
    version = _resolve_version(metadata, meta)

    # Canonical fixtures must themselves satisfy the spec — fail the seed
    # loudly rather than ship a non-compliant `@posthog/*` template.
    try:
        validate_skill_spec(
            name=slug,
            description=description,
            compatibility=compatibility,
            metadata=metadata,
            allowed_tools=allowed_tools,
        )
    except SkillSpecError as exc:
        raise CommandError(f"canonical skill {slug!r}: {exc.message}") from exc
    return _CanonicalSkill(slug, description, license, compatibility, metadata, allowed_tools, version, body, files)


def _parse_allowed_tools(raw: Any) -> list[str]:
    """Accept the spec's space-separated `allowed-tools` string or a YAML list."""
    if isinstance(raw, str):
        return raw.split()
    if isinstance(raw, list):
        return [str(t) for t in raw]
    return []


def _resolve_version(metadata: dict[str, str], meta: dict[str, Any]) -> int:
    """Registry-row version: `metadata.version`, falling back to a legacy top-level `version`."""
    version_raw = metadata.get("version", meta.get("version", 1))
    try:
        return int(version_raw)
    except (TypeError, ValueError):
        return 1


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body) for a markdown file.

    If the file starts with a `---` YAML frontmatter block, parse it and
    return the post-frontmatter content as the body. No frontmatter → empty
    dict + the full text.
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing `---` on a line by itself.
    rest = text[3:]
    end_index = rest.find("\n---")
    if end_index == -1:
        return {}, text
    frontmatter_text = rest[:end_index]
    body = rest[end_index + 4 :].lstrip("\n")
    try:
        meta = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body
