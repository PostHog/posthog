"""Resolve a draft revision's skill references against the llma-skill store.

A draft revision can reference versioned skills in the store via
``AgentRevision.skill_refs`` — each entry is ``{from_template, alias, version?}``
where ``from_template`` is the store skill *name* (human-readable, stable across
versions) and ``version`` optionally pins a specific published version.

At freeze the references are resolved to their pinned bytes and materialized
into the bundle (``skills/<alias>/SKILL.md`` + companions) so a frozen revision
never re-resolves a possibly-changed skill at runtime. Resolution happens here,
in Django, because the store lives in the main DB the janitor cannot reach; the
resolved files are pushed into the bundle through the existing janitor proxy.
"""

from dataclasses import dataclass

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.skills.backend.api.skill_services import get_skill_by_name_from_db
from products.skills.backend.marketplace.adapters import load_skill_export
from products.skills.backend.marketplace.packaging import render_skill_md, validate_for_export


@dataclass(frozen=True)
class ResolvedSkill:
    """A store skill resolved to its bundle-ready form plus freeze provenance."""

    alias: str
    # `body` is the *rendered* SKILL.md (frontmatter + body) so the janitor's
    # freeze-time `deriveSkillDescription` reads the curated `description:` from
    # frontmatter rather than falling back to the first prose line.
    body: str
    files: list[dict[str, str]]
    description: str
    # Provenance stamped onto the frozen SkillRef. `from_template` is the
    # human-readable name; `source_version_id` is the immutable per-version row
    # UUID — a readable reference plus an exact anchor.
    from_template: str
    version: int
    source_version_id: str

    def put_skill_payload(self) -> dict:
        """The body for the janitor `PUT /revisions/:id/skills/:alias` call."""
        return {"description": self.description, "body": self.body, "files": self.files}


def assert_skill_refs_readable(
    team: Team,
    refs: list[dict],
    *,
    scopes: list[str] | None,
    user_access_control: UserAccessControl,
) -> None:
    """Authorize the caller to read every referenced store skill before it can be
    materialized into a bundle.

    Freeze and ``set_skill_refs`` pull ``llm_skill`` content into the agent
    bundle, which is then readable through the ``agents:read`` bundle APIs. So
    they must honour the same boundary ``LLMSkillViewSet`` enforces: the
    ``llm_skill:read`` API scope for token callers, plus object-level access
    control for everyone. Without this an ``agents:write`` token (or an
    RBAC-restricted user) could exfiltrate a private skill by freezing it into a
    bundle and reading it back. ``scopes`` is ``None`` for session auth, which
    carries no API scopes and is governed solely by object-level access control.
    """
    names: list[str] = []
    for ref in refs:
        name = ref.get("from_template")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    if not names:
        return
    # Cross-resource API-scope check for token callers (personal API key / OAuth).
    if scopes is not None and not ({"*", "llm_skill:read", "llm_skill:write"} & set(scopes)):
        raise PermissionDenied(
            "Referencing skill store skills requires the `llm_skill:read` scope in addition to `agents:write`."
        )
    # Object-level access control, mirroring LLMSkillViewSet's AccessControlPermission.
    # A missing skill is left to resolve_skill_ref to reject loudly at freeze.
    for name in names:
        skill = get_skill_by_name_from_db(team, name)
        if skill is not None and not user_access_control.check_access_level_for_object(skill, "viewer"):
            raise PermissionDenied(
                f"You do not have read access to the skill '{name}' in the skill store. Ask a skill admin to "
                "share it with you, or remove it from the agent's skill references."
            )


def resolve_skill_ref(team: Team, ref: dict) -> ResolvedSkill:
    """Resolve one ``{from_template, alias, version?}`` ref to a ``ResolvedSkill``.

    Fails loud (``ValidationError``) on a malformed ref, a missing/deleted
    pinned version, or a skill that isn't export-ready under the Agent Skills
    spec — freeze must never silently ship an empty or partial skill.
    """
    name = ref.get("from_template")
    alias = ref.get("alias")
    version = ref.get("version")
    # `source_version_id` is the immutable per-version row UUID a prior freeze
    # stamped back onto the ref. When present it pins the exact version row —
    # the truly immortal anchor — so a forked re-freeze can't drift to "latest".
    source_version_id = ref.get("source_version_id")
    if not name or not alias:
        known = alias or name
        label = f" '{known}'" if known else ""
        raise ValidationError(f"A skill reference{label} is missing its required 'from_template' or 'alias'.")
    if version is not None and not isinstance(version, int):
        raise ValidationError(f"Skill reference '{alias}' has a non-integer version: {version!r}")

    # A pinned `source_version_id` targets one immutable version row — resolve it
    # even if the skill was later archived, so the pin stays the immortal anchor.
    skill = get_skill_by_name_from_db(team, name, version, source_version_id, include_archived=bool(source_version_id))
    if skill is None:
        pinned = (
            f" {source_version_id}" if source_version_id else f" v{version}" if version is not None else " (latest)"
        )
        raise ValidationError(f"Skill '{name}'{pinned} referenced by '{alias}' was not found in the store.")

    export = load_skill_export(skill)
    problems = validate_for_export(export)
    if problems:
        raise ValidationError(
            f"Skill '{name}' v{skill.version} referenced by '{alias}' is not export-ready: {'; '.join(problems)}"
        )

    return ResolvedSkill(
        alias=alias,
        body=render_skill_md(export),
        files=[{"path": f.path, "content": f.content} for f in export.files],
        description=export.description,
        from_template=name,
        version=skill.version,
        source_version_id=str(skill.id),
    )


def stamp_skill_provenance(derived_spec: dict, provenance_by_alias: dict[str, dict]) -> None:
    """Merge freeze provenance onto the derived SkillRefs, matching by id == alias.

    The janitor derives content-based skill refs (``{id, path, description}``)
    where ``id`` is the bundle folder name — i.e. the alias we materialized the
    skill under. This stamps ``from_template``/``version``/``source_version_id``
    back on so the frozen spec records each store-sourced skill's provenance.
    Mutates ``derived_spec`` in place.
    """
    for skill in derived_spec.get("skills") or []:
        prov = provenance_by_alias.get(skill.get("id"))
        if prov:
            skill.update(prov)
