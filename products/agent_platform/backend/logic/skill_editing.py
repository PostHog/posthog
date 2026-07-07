"""Store-backed editing of a draft revision's referenced skills.

Skills are store-only: freeze resolves ``AgentRevision.skill_refs`` against the
llma-skill store, materializes the pinned bytes into the bundle, and sweeps any
``skills/`` folder that isn't a current ref (see the freeze action). Writing a
skill's markdown into the draft bundle therefore can't stick — it would be
overwritten (ref alias) or deleted (orphan) at the next freeze. Instead an edit
publishes a new version of the store skill and the caller re-pins the draft's
ref to it, so the next freeze materializes exactly the edited bytes and the
store stays the single source of truth.
"""

from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl

from products.skills.backend.api.skill_services import (
    LLMSkillDuplicateNameConflictError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    create_skill,
    get_skill_by_name_from_db,
    publish_skill_version,
)
from products.skills.backend.marketplace.packaging import SkillImportError, parse_skill_md
from products.skills.backend.models import LLMSkill


class SkillStoreConflict(APIException):
    """The store skill changed between read and publish — caller should reload
    the latest version and retry. Plain string detail on purpose: exceptions_hog
    can't render dict details (see JanitorUpstreamError)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The skill changed in the store since you loaded it. Reload the latest version and try again."
    default_code = "skill_store_conflict"


def assert_skills_writable(
    team: Team,
    names: list[str],
    *,
    scopes: list[str] | None,
    user_access_control: UserAccessControl,
) -> None:
    """Authorize the caller to publish new versions of every named store skill.

    The write-side mirror of ``assert_skill_refs_readable``: these edits mutate
    ``llm_skill`` rows shared across every agent that references them, so they
    must honour the same boundary ``LLMSkillViewSet`` enforces on PATCH — the
    ``llm_skill:write`` API scope for token callers, plus editor-level object
    access for everyone. Without this an ``agents:write`` token could rewrite a
    shared skill through the agent authoring surface. ``scopes`` is ``None`` for
    session auth, which carries no API scopes and is governed solely by
    object-level access control.
    """
    unique_names: list[str] = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)
    if not unique_names:
        return
    if scopes is not None and not ({"*", "llm_skill:write"} & set(scopes)):
        raise PermissionDenied(
            "Editing store-backed skills requires the `llm_skill:write` scope in addition to `agents:write`."
        )
    for name in unique_names:
        skill = get_skill_by_name_from_db(team, name)
        if skill is None:
            # A missing name means the import will CREATE a shared store skill.
            # Mirror LLMSkillViewSet's create gate (resource-level editor access)
            # so an agent editor without llm_skill create rights can't mint
            # team-wide skills through the agent surface.
            if not user_access_control.check_access_level_for_resource("llm_skill", "editor"):
                raise PermissionDenied(
                    f"You do not have access to create the skill '{name}' in the skill store. Ask a skill "
                    "admin for editor access to skills, or import only skills that already exist."
                )
        elif not user_access_control.check_access_level_for_object(skill, "editor"):
            raise PermissionDenied(
                f"You do not have edit access to the skill '{name}' in the skill store. Ask a skill admin to "
                "grant you editor access, or remove it from the agent's skill references."
            )


def store_skill_exists(team: Team, name: str) -> bool:
    """Whether an active (non-archived) store skill with this name exists."""
    return get_skill_by_name_from_db(team, name) is not None


def _publish_next_version(team: Team, *, user: User, skill_name: str, fields: dict[str, Any]) -> LLMSkill:
    """Publish ``fields`` on top of the store's latest version, mapping the
    service errors to API-shaped ones. Publishing targets latest — an edit means
    "move the skill forward", even when the draft's ref pins an older version;
    the caller re-pins the ref to the returned row.
    """
    latest = get_skill_by_name_from_db(team, skill_name)
    if latest is None:
        raise ValidationError(
            f"Skill '{skill_name}' was not found in the skill store. It may have been archived — "
            "remove the reference or recreate the skill."
        )
    try:
        return publish_skill_version(team, user=user, skill_name=skill_name, base_version=latest.version, **fields)
    except LLMSkillNotFoundError:
        raise ValidationError(f"Skill '{skill_name}' was not found in the skill store.")
    except LLMSkillVersionConflictError:
        raise SkillStoreConflict()
    except LLMSkillVersionLimitError as e:
        raise ValidationError(
            f"Skill '{skill_name}' has reached the maximum of {e.max_version} versions. "
            "Archive and recreate the skill to continue publishing."
        )


def publish_skill_body(
    team: Team,
    *,
    user: User,
    skill_name: str,
    body: str,
    description: str | None = None,
) -> LLMSkill:
    """Publish ``body`` (and optionally ``description``) as a new version of the
    named store skill; omitted fields carry forward from the current version."""
    return _publish_next_version(
        team, user=user, skill_name=skill_name, fields={"body": body, "description": description}
    )


def publish_skill_md_edit(team: Team, *, user: User, skill_name: str, content: str) -> LLMSkill:
    """Publish edited SKILL.md content as a new version of the named store skill.

    The bundle's SKILL.md is ``render_skill_md`` output (frontmatter + body), so
    an edited file normally round-trips through ``parse_skill_md`` — frontmatter
    fields (description, license, compatibility, allowed-tools, metadata) update
    the store alongside the body. Content without a frontmatter block is
    accepted as body-only (the other fields carry forward), but a block that
    *looks* like frontmatter and fails to parse is rejected — storing it as body
    would double the frontmatter on the next freeze render.
    """
    parsed: dict[str, Any] | None
    try:
        parsed = parse_skill_md(content)
    except SkillImportError as e:
        if content.startswith("---"):
            raise ValidationError(f"SKILL.md frontmatter is invalid: {e}")
        parsed = None
    if parsed is None:
        fields: dict[str, Any] = {"body": content}
    else:
        fields = {
            "body": parsed["body"],
            # An empty parsed field means the frontmatter dropped it — carry the
            # current value forward rather than blanking a shared field.
            "description": parsed["description"] or None,
            "license": parsed["license"] or None,
            "compatibility": parsed["compatibility"] or None,
            "allowed_tools": parsed["allowed_tools"] or None,
            "metadata": parsed["metadata"] or None,
        }
    return _publish_next_version(team, user=user, skill_name=skill_name, fields=fields)


def create_store_skill(team: Team, *, user: User, name: str, description: str, body: str) -> LLMSkill:
    """Create a brand-new store skill (v1) for a bulk-imported skill id."""
    try:
        return create_skill(team, user=user, name=name, description=description, body=body)
    except LLMSkillDuplicateNameConflictError:
        # A concurrent create won the race — surface as a conflict so the caller
        # retries and takes the publish-new-version path instead.
        raise SkillStoreConflict(f"A skill named '{name}' was just created in the store. Retry the import.")
