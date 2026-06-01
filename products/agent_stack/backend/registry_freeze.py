"""
Freeze-time resolution of registry template refs.

A draft revision's `spec` JSONB carries:

    spec.skills[].from_template = "<AgentSkillTemplate uuid>"  # optional
    spec.skills[].version       = <pinned> | omitted (= latest)
    spec.skills[].alias         = "<bundle dir name>"

    spec.tools[].kind == "custom_template"
    spec.tools[].from_template  = "<AgentCustomToolTemplate uuid>"
    spec.tools[].version        = <pinned> | omitted
    spec.tools[].alias          = "<bundle dir name>"

At `/revisions/<id>/freeze` time the Django side:

1. Resolves each `from_template` to a concrete row at the requested
   version (or `is_latest=True` if unpinned).
2. Copies the resolved content into the bundle via the janitor proxy
   (`bundle/skills/<alias>.md` + files; `bundle/tools/<alias>/{source.ts,compiled.js}`).
3. Stamps the resolved `version` back into the spec entry so the
   frozen revision is reproducible.
4. Inserts one join row per ref (`AgentRevisionSkillTemplate`,
   `AgentRevisionCustomToolTemplate`) and one per native tool id
   (`AgentRevisionNativeTool`) — these make the "Used by" panel and the
   referential-integrity guarantee work.

The whole thing runs inside the caller's `transaction.atomic()`. The
bundle writes are HTTP calls into the janitor — they're not transactional,
but if a DB write fails after a bundle copy, the revision stays draft
and the next freeze attempt is idempotent (it overwrites the same
bundle paths and the join row inserts hit a clean revision).

Specs that carry no `from_template` refs are left untouched; this lets
the freeze pipeline run unconditionally without breaking legacy specs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Q

from .janitor_client import JanitorClient
from .models import (
    AgentCustomToolTemplate,
    AgentRevision,
    AgentRevisionCustomToolTemplate,
    AgentRevisionNativeTool,
    AgentRevisionSkillTemplate,
    AgentSkillTemplate,
)


class FreezeError(Exception):
    """Raised when a freeze-time resolution can't be completed.

    Holds a human-readable message + an optional pointer at the offending
    spec entry so the viewset can surface a 400-ish error to authoring
    clients (UI + MCP).
    """

    def __init__(self, message: str, *, kind: str | None = None, index: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind  # 'skill' | 'tool' | 'native'
        self.index = index


@dataclass
class FreezeResult:
    """Summary of what freeze_templates_into_bundle just did.

    Mostly for tests + the viewset response — production code path doesn't
    inspect the returned object beyond logging.
    """

    skill_refs: list[AgentRevisionSkillTemplate]
    custom_tool_refs: list[AgentRevisionCustomToolTemplate]
    native_tool_refs: list[AgentRevisionNativeTool]
    resolved_spec: dict[str, Any]


def freeze_templates_into_bundle(
    revision: AgentRevision,
    janitor: JanitorClient,
    *,
    team_id: int,
) -> FreezeResult:
    """Resolve `from_template` refs, copy content into the bundle, insert join rows.

    Caller is responsible for opening the `transaction.atomic()` block —
    we want the spec-update + join inserts to commit (or roll back) as
    one unit. Bundle writes happen inside the block but are HTTP calls
    that can't participate in the DB transaction; re-running freeze
    cleans up after itself.
    """
    spec = dict(revision.spec or {})
    skills = list(spec.get("skills", []) or [])
    tools = list(spec.get("tools", []) or [])

    skill_refs: list[AgentRevisionSkillTemplate] = []
    custom_tool_refs: list[AgentRevisionCustomToolTemplate] = []
    native_tool_refs: list[AgentRevisionNativeTool] = []

    # Wipe any prior join rows from a previous freeze attempt — freeze is
    # idempotent and the alias unique index would otherwise reject re-runs.
    AgentRevisionSkillTemplate.objects.filter(revision=revision).delete()
    AgentRevisionCustomToolTemplate.objects.filter(revision=revision).delete()
    AgentRevisionNativeTool.objects.filter(revision=revision).delete()

    # ---- skills ----
    for i, skill in enumerate(skills):
        if not isinstance(skill, dict) or "from_template" not in skill:
            continue
        template = _resolve_skill_template(skill, team_id=team_id, index=i)
        alias = _require_alias(skill, kind="skill", index=i)
        _write_skill_to_bundle(janitor, str(revision.id), template, alias)
        # Stamp the runtime-required fields so the post-freeze spec passes
        # the runner's `SkillRefSchema` zod check without relying on its
        # default permissiveness. The `from_template + version + alias`
        # lineage rides through as extra keys (preserved on the JSONB row
        # but stripped from the parsed runtime view).
        skill["id"] = alias
        skill["path"] = f"skills/{alias}.md"
        skill.setdefault("description", template.description)
        skill["version"] = template.version
        skill_refs.append(
            AgentRevisionSkillTemplate.objects.create(
                revision=revision,
                skill_template=template,
                pinned_version=template.version,
                alias=alias,
                ordinal=i,
            )
        )

    # ---- tools ----
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        kind = tool.get("kind")
        if kind == "custom_template":
            template_t = _resolve_custom_tool_template(tool, team_id=team_id, index=i)
            alias = _require_alias(tool, kind="tool", index=i)
            _write_custom_tool_to_bundle(janitor, str(revision.id), template_t, alias)
            # Reshape the spec entry into the runtime `ToolRefSchema`
            # `custom` variant — `kind: custom`, `id`, `path` — so the
            # runner can dispatch through the existing custom-tool path.
            # `from_template + version + alias` carry the registry
            # lineage on the JSONB row.
            tool["kind"] = "custom"
            tool["id"] = alias
            tool["path"] = f"tools/{alias}/"
            tool["version"] = template_t.version
            custom_tool_refs.append(
                AgentRevisionCustomToolTemplate.objects.create(
                    revision=revision,
                    tool_template=template_t,
                    pinned_version=template_t.version,
                    alias=alias,
                    ordinal=i,
                )
            )
        elif kind == "native":
            tool_id = tool.get("id")
            if not isinstance(tool_id, str) or not tool_id:
                raise FreezeError(f"spec.tools[{i}] (native) missing `id`.", kind="native", index=i)
            native_tool_refs.append(
                AgentRevisionNativeTool.objects.create(
                    revision=revision,
                    native_tool_id=tool_id,
                    ordinal=i,
                )
            )

    spec["skills"] = skills
    spec["tools"] = tools

    # Persist the spec only if we actually touched it — keeps the
    # AgentRevision.updated_at stable for no-op freezes (specs without
    # any from_template refs).
    if skill_refs or custom_tool_refs or _any_native_tool(tools):
        revision.spec = spec
        revision.save(update_fields=["spec"])

    return FreezeResult(
        skill_refs=skill_refs,
        custom_tool_refs=custom_tool_refs,
        native_tool_refs=native_tool_refs,
        resolved_spec=spec,
    )


# ── resolvers ──────────────────────────────────────────────────────────────


def _resolve_skill_template(skill: dict[str, Any], *, team_id: int, index: int) -> AgentSkillTemplate:
    template_id = skill.get("from_template")
    if not isinstance(template_id, str) or not template_id:
        raise FreezeError(
            f"spec.skills[{index}].from_template must be a UUID string.",
            kind="skill",
            index=index,
        )
    base_qs = AgentSkillTemplate.objects.filter(pk=template_id, deleted=False)
    # Templates are visible to the team that owns them, or are canonical
    # (`team_id IS NULL`). Refuse silently-shared rows that belong to a
    # different team.
    base_qs = base_qs.filter(Q(team_id=team_id) | Q(team_id__isnull=True))
    pinned = skill.get("version")
    if pinned is None:
        template = base_qs.filter(is_latest=True).first()
    else:
        try:
            pinned_int = int(pinned)
        except (TypeError, ValueError) as exc:
            raise FreezeError(
                f"spec.skills[{index}].version must be an integer.",
                kind="skill",
                index=index,
            ) from exc
        template = base_qs.filter(version=pinned_int).first()
    if template is None:
        raise FreezeError(
            f"spec.skills[{index}] references unknown / archived skill template "
            f"{template_id!r} (version={skill.get('version')!r}).",
            kind="skill",
            index=index,
        )
    return template


def _resolve_custom_tool_template(tool: dict[str, Any], *, team_id: int, index: int) -> AgentCustomToolTemplate:
    template_id = tool.get("from_template")
    if not isinstance(template_id, str) or not template_id:
        raise FreezeError(
            f"spec.tools[{index}].from_template must be a UUID string.",
            kind="tool",
            index=index,
        )
    base_qs = AgentCustomToolTemplate.objects.filter(pk=template_id, deleted=False)
    base_qs = base_qs.filter(Q(team_id=team_id) | Q(team_id__isnull=True))
    pinned = tool.get("version")
    if pinned is None:
        template = base_qs.filter(is_latest=True).first()
    else:
        try:
            pinned_int = int(pinned)
        except (TypeError, ValueError) as exc:
            raise FreezeError(
                f"spec.tools[{index}].version must be an integer.",
                kind="tool",
                index=index,
            ) from exc
        template = base_qs.filter(version=pinned_int).first()
    if template is None:
        raise FreezeError(
            f"spec.tools[{index}] references unknown / archived custom tool template "
            f"{template_id!r} (version={tool.get('version')!r}).",
            kind="tool",
            index=index,
        )
    return template


# ── bundle writers ────────────────────────────────────────────────────────


def _write_skill_to_bundle(
    janitor: JanitorClient,
    revision_id: str,
    template: AgentSkillTemplate,
    alias: str,
) -> None:
    """Copy `template.body` + companion files into the bundle.

    Layout matches the plan: `bundle/skills/<alias>.md` (the SKILL.md)
    plus `bundle/skills/<alias>/<file_path>` for each companion file.
    """
    janitor.put_file(revision_id, f"skills/{alias}.md", template.body)
    for f in template.files.all():
        janitor.put_file(revision_id, f"skills/{alias}/{f.path}", f.content)


def _write_custom_tool_to_bundle(
    janitor: JanitorClient,
    revision_id: str,
    template: AgentCustomToolTemplate,
    alias: str,
) -> None:
    """Copy `source` + `compiled_js` + `schema.json` into `bundle/tools/<alias>/`.

    Layout matches what the runner's InProcessSandbox expects (see
    `services/agent-tests/src/cases/custom-tool-sandbox.test.ts`): each
    tool directory holds the three siblings, and the runner reads
    `compiled.js` to execute + `schema.json` for the args/returns
    metadata it surfaces to the model.
    """
    janitor.put_file(revision_id, f"tools/{alias}/source.ts", template.source)
    janitor.put_file(revision_id, f"tools/{alias}/compiled.js", template.compiled_js)
    schema = {
        "description": template.description or "",
        "args": template.args_schema or {"type": "object"},
        "returns": template.returns_schema or {},
        "requires_secrets": list(template.requires_secrets or []),
    }
    janitor.put_file(revision_id, f"tools/{alias}/schema.json", json.dumps(schema))


# ── small helpers ─────────────────────────────────────────────────────────


def _require_alias(entry: dict[str, Any], *, kind: str, index: int) -> str:
    alias = entry.get("alias")
    if not isinstance(alias, str) or not alias:
        raise FreezeError(
            f"spec.{kind}s[{index}] missing required `alias` (used as the bundle directory name).",
            kind=kind,
            index=index,
        )
    return alias


def _any_native_tool(tools: list[Any]) -> bool:
    return any(isinstance(t, dict) and t.get("kind") == "native" for t in tools)


@transaction.atomic
def run_freeze_resolution(
    revision: AgentRevision,
    janitor: JanitorClient,
    *,
    team_id: int,
) -> FreezeResult:
    """Atomic wrapper around `freeze_templates_into_bundle` for callers
    that just want one entrypoint. Use the unwrapped variant when the
    caller is already inside an atomic block (e.g. composing with
    additional writes).
    """
    return freeze_templates_into_bundle(revision, janitor, team_id=team_id)
