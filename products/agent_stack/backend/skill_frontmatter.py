"""
Agent Skills spec compliance for the registry.

Two jobs:

1. `assemble_skill_md` — turn a registry skill row (structured DB columns
   + authored body) into a single, spec-compliant `SKILL.md` string: one
   authoritative YAML frontmatter block followed by the body. This is what
   freeze writes into `bundle/skills/<alias>/SKILL.md`.

2. `validate_skill_spec` — server-side mirror of `skills-ref validate`
   (https://agentskills.io/specification.md) so authoring clients (UI +
   MCP) get the same rejection the reference validator would give, at
   create / publish time rather than at freeze.

The registry `name` (which may carry the `@posthog/` prefix) is the
*registry identity*. The spec `name` emitted into the frozen SKILL.md is
the bundle-directory **alias** — a bare slug that must equal its parent
directory per the spec. The two are validated separately on purpose.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

# Spec name rule: 1–64 lowercase alphanumerics and hyphens, no leading /
# trailing hyphen, no consecutive hyphens. The grammar below rejects `--`
# inherently (each hyphen must be followed by an alphanumeric run).
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500


class SkillSpecError(ValueError):
    """A skill's frontmatter violates the Agent Skills spec.

    Carries a `field` pointer so callers (serializer, freeze) can attach
    the message to the right input.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def validate_skill_name(name: str) -> str:
    if not name:
        raise SkillSpecError("Skill name is required.", field="name")
    if len(name) > NAME_MAX:
        raise SkillSpecError(f"Skill name must be at most {NAME_MAX} characters.", field="name")
    if not SKILL_NAME_RE.match(name):
        raise SkillSpecError(
            "Skill name must be lowercase letters, digits, and single hyphens "
            "(no leading / trailing / consecutive hyphens).",
            field="name",
        )
    return name


def validate_description(description: str) -> str:
    # Spec: required, 1–1024, non-empty.
    stripped = (description or "").strip()
    if not stripped:
        raise SkillSpecError("Description is required and must be non-empty.", field="description")
    if len(description) > DESCRIPTION_MAX:
        raise SkillSpecError(f"Description must be at most {DESCRIPTION_MAX} characters.", field="description")
    return description


def validate_compatibility(compatibility: str) -> str:
    # Optional; only constrained when present.
    if compatibility and len(compatibility) > COMPATIBILITY_MAX:
        raise SkillSpecError(
            f"Compatibility must be at most {COMPATIBILITY_MAX} characters.",
            field="compatibility",
        )
    return compatibility


def validate_metadata_map(metadata: Any) -> dict[str, str]:
    # Spec: metadata is a map of string keys to string values.
    if metadata in (None, ""):
        return {}
    if not isinstance(metadata, dict):
        raise SkillSpecError("Metadata must be a mapping of string keys to string values.", field="metadata")
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SkillSpecError(
                "Metadata keys and values must both be strings.",
                field="metadata",
            )
    return metadata


def validate_allowed_tools(allowed_tools: Any) -> list[str]:
    # Stored as a list internally; emitted as a space-separated string in
    # frontmatter (the spec's `allowed-tools` shape). Tool ids can't carry
    # spaces because the spec joins on whitespace.
    if allowed_tools in (None, ""):
        return []
    if not isinstance(allowed_tools, list) or not all(isinstance(t, str) for t in allowed_tools):
        raise SkillSpecError("allowed_tools must be a list of strings.", field="allowed_tools")
    for tool in allowed_tools:
        if " " in tool:
            raise SkillSpecError(
                f"allowed_tools entry {tool!r} must not contain spaces "
                "(the spec serializes them as a space-separated list).",
                field="allowed_tools",
            )
    return allowed_tools


def validate_skill_spec(
    *,
    name: str,
    description: str,
    compatibility: str = "",
    metadata: Any = None,
    allowed_tools: Any = None,
) -> None:
    """Raise `SkillSpecError` if any field violates the Agent Skills spec.

    `name` here is the spec name (bundle alias / bare slug). The registry
    `@posthog/<slug>` identity is validated separately by the serializer.
    """
    validate_skill_name(name)
    validate_description(description)
    validate_compatibility(compatibility)
    validate_metadata_map(metadata)
    validate_allowed_tools(allowed_tools)


_FRONTMATTER_RE = re.compile(r"\A﻿?---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)


def strip_frontmatter(body: str) -> str:
    """Drop a leading YAML frontmatter block from an authored body.

    Authors sometimes paste a full `SKILL.md` (frontmatter included) into
    the body field. `assemble_skill_md` is the single authoritative source
    of frontmatter, so we strip any the body carries to avoid a duplicate /
    conflicting block in the frozen artifact.
    """
    return _FRONTMATTER_RE.sub("", body, count=1).lstrip("\n")


def assemble_skill_md(
    *,
    alias: str,
    description: str,
    body: str,
    license: str = "",
    compatibility: str = "",
    metadata: dict[str, str] | None = None,
    allowed_tools: list[str] | None = None,
) -> str:
    """Build a spec-compliant `SKILL.md` string.

    Frontmatter field order follows the spec's documentation order. `name`
    is the bundle-dir alias (so it matches the parent directory). Optional
    fields are omitted when empty rather than emitted blank.
    """
    # The alias is emitted verbatim as the spec `name`, so enforce the spec
    # slug here at the point of emission — not only at the freeze call site.
    # This keeps the alias→name invariant intact for any future caller
    # (admin re-render, backfill, repair script) that doesn't route through
    # `_require_alias`.
    validate_skill_name(alias)
    front: dict[str, Any] = {"name": alias, "description": description}
    if license:
        front["license"] = license
    if compatibility:
        front["compatibility"] = compatibility
    if allowed_tools:
        front["allowed-tools"] = " ".join(allowed_tools)
    if metadata:
        front["metadata"] = dict(metadata)

    frontmatter = yaml.safe_dump(front, sort_keys=False, default_flow_style=False, allow_unicode=True).strip()
    stripped_body = strip_frontmatter(body)
    return f"---\n{frontmatter}\n---\n\n{stripped_body}".rstrip() + "\n"
