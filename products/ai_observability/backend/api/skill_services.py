from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from posthog.models import Team, User

from ..models.skills import LLMSkill, LLMSkillFile, annotate_llm_skill_version_history_metadata

MAX_SKILL_VERSION = 2000
MAX_SKILL_BODY_BYTES = 1_000_000
MAX_SKILL_FILE_BYTES = 1_000_000
MAX_SKILL_FILE_COUNT = 50


class LLMSkillNotFoundError(Exception):
    pass


@dataclass
class LLMSkillVersionConflictError(Exception):
    current_version: int


@dataclass
class LLMSkillVersionLimitError(Exception):
    max_version: int


@dataclass
class LLMSkillFileLimitError(Exception):
    max_count: int


@dataclass
class LLMSkillEditError(Exception):
    # `file_path` extends this dataclass (rather than a subclass) so the publish view can catch a
    # single exception type for both body edits and per-file edits. `edit_index` is optional because
    # path-level failures (e.g. missing file) aren't tied to any particular edit.
    message: str
    edit_index: int | None = None
    file_path: str | None = None


class LLMSkillDuplicateNameConflictError(Exception):
    pass


@dataclass
class LLMSkillFilePathConflictError(Exception):
    path: str


@dataclass
class LLMSkillFileNotFoundError(Exception):
    path: str


def apply_skill_body_edits(body: str, edits: list[dict[str, str]]) -> str:
    """Apply sequential find/replace edits to a skill body.

    Each edit's 'old' text must match exactly once in the current body.
    """
    text = body
    for i, edit in enumerate(edits):
        old = edit["old"]
        new = edit["new"]
        count = text.count(old)
        if count == 0:
            raise LLMSkillEditError(
                message="Text to replace was not found in the skill body.",
                edit_index=i,
            )
        if count > 1:
            raise LLMSkillEditError(
                message=f"Text to replace matches {count} times — provide more context to make it unique.",
                edit_index=i,
            )
        text = text.replace(old, new, 1)

    if len(text.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise LLMSkillEditError(
            message=f"Resulting skill body exceeds the {MAX_SKILL_BODY_BYTES} byte size limit.",
            edit_index=len(edits) - 1,
        )

    return text


def get_active_skill_queryset(team: Team) -> QuerySet[LLMSkill]:
    return annotate_llm_skill_version_history_metadata(
        LLMSkill.objects.filter(team=team, deleted=False).select_related("created_by")
    )


def get_latest_skills_queryset(team: Team) -> QuerySet[LLMSkill]:
    return get_active_skill_queryset(team).filter(is_latest=True)


def get_skill_by_name_from_db(
    team: Team,
    skill_name: str,
    version: int | None = None,
    version_id: str | None = None,
) -> LLMSkill | None:
    queryset = get_active_skill_queryset(team).filter(name=skill_name)

    if version_id is not None:
        queryset = queryset.filter(id=version_id)
        if version is not None:
            queryset = queryset.filter(version=version)
        return queryset.order_by("created_at", "id").first()

    if version is None:
        return queryset.filter(is_latest=True).order_by("-version", "-created_at", "-id").first()

    return queryset.filter(version=version).order_by("created_at", "id").first()


def resolve_versions_page(
    team: Team,
    skill_name: str,
    *,
    limit: int,
    offset: int | None = None,
    before_version: int | None = None,
) -> tuple[list[LLMSkill], bool]:
    queryset = (
        LLMSkill.objects.filter(team=team, name=skill_name, deleted=False)
        .select_related("created_by")
        .order_by("-version", "-created_at", "-id")
    )

    if before_version is not None:
        queryset = queryset.filter(version__lt=before_version)
    elif offset is not None:
        versions = list(queryset[offset : offset + limit + 1])
        has_more = len(versions) > limit
        return versions[:limit], has_more

    versions = list(queryset[: limit + 1])
    has_more = len(versions) > limit
    return versions[:limit], has_more


def _carry_forward(payload_value: Any, current_value: Any) -> Any:
    return payload_value if payload_value is not None else current_value


def apply_skill_file_edits(file_content: str, edits: list[dict[str, str]], *, file_path: str) -> str:
    """Apply sequential find/replace edits to a single bundled skill file.

    Each edit's 'old' text must match exactly once. Result size capped at MAX_SKILL_FILE_BYTES.
    """
    text = file_content
    for i, edit in enumerate(edits):
        old = edit["old"]
        new = edit["new"]
        count = text.count(old)
        if count == 0:
            raise LLMSkillEditError(
                message=f"Text to replace was not found in file '{file_path}'.",
                edit_index=i,
                file_path=file_path,
            )
        if count > 1:
            raise LLMSkillEditError(
                message=(
                    f"Text to replace matches {count} times in file '{file_path}' — "
                    "provide more context to make it unique."
                ),
                edit_index=i,
                file_path=file_path,
            )
        text = text.replace(old, new, 1)

    if len(text.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
        raise LLMSkillEditError(
            message=f"Edited file '{file_path}' exceeds the {MAX_SKILL_FILE_BYTES} byte size limit.",
            edit_index=len(edits) - 1,
            file_path=file_path,
        )

    return text


def publish_skill_version(
    team: Team,
    *,
    user: User,
    skill_name: str,
    body: str | None = None,
    edits: list[dict[str, str]] | None = None,
    description: str | None = None,
    license: str | None = None,
    compatibility: str | None = None,
    allowed_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    files: list[dict[str, str]] | None = None,
    file_edits: list[dict[str, Any]] | None = None,
    base_version: int,
) -> LLMSkill:
    with transaction.atomic():
        current_latest = (
            LLMSkill.objects.select_for_update()
            .filter(team=team, name=skill_name, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if current_latest is None:
            raise LLMSkillNotFoundError()

        if base_version != current_latest.version:
            raise LLMSkillVersionConflictError(current_version=current_latest.version)
        if current_latest.version >= MAX_SKILL_VERSION:
            raise LLMSkillVersionLimitError(max_version=MAX_SKILL_VERSION)

        if edits is not None:
            resolved_body = apply_skill_body_edits(current_latest.body, edits)
        else:
            resolved_body = _carry_forward(body, current_latest.body)

        resolved_file_edits: dict[str, str] | None = None
        if file_edits is not None:
            resolved_file_edits = _resolve_file_edits(current_latest, file_edits)

        LLMSkill.objects.filter(pk=current_latest.pk).update(is_latest=False)
        published_skill = LLMSkill.objects.create(
            team=team,
            name=current_latest.name,
            description=_carry_forward(description, current_latest.description),
            body=resolved_body,
            license=_carry_forward(license, current_latest.license),
            compatibility=_carry_forward(compatibility, current_latest.compatibility),
            allowed_tools=_carry_forward(allowed_tools, current_latest.allowed_tools),
            metadata=_carry_forward(metadata, current_latest.metadata),
            version=current_latest.version + 1,
            is_latest=True,
            created_by=user,
        )

        if files is not None:
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(
                        skill=published_skill,
                        path=file_data["path"],
                        content=file_data["content"],
                        content_type=file_data.get("content_type", "text/plain"),
                    )
                    for file_data in files
                ]
            )
        else:
            _copy_files(current_latest, published_skill, edited_content=resolved_file_edits)

        refreshed = get_active_skill_queryset(team).filter(pk=published_skill.pk).first()
        return refreshed if refreshed is not None else published_skill


def _resolve_file_edits(current_skill: LLMSkill, file_edits: list[dict[str, Any]]) -> dict[str, str]:
    """Apply each file's edits against the current file content; return {path: new_content}."""
    source_files = {f.path: f for f in LLMSkillFile.objects.filter(skill=current_skill)}
    resolved: dict[str, str] = {}
    for entry in file_edits:
        path = entry["path"]
        if path not in source_files:
            raise LLMSkillEditError(
                message=f"File '{path}' not found in the current skill version.",
                file_path=path,
            )
        resolved[path] = apply_skill_file_edits(
            source_files[path].content,
            entry["edits"],
            file_path=path,
        )
    return resolved


def _copy_files(
    source_skill: LLMSkill,
    target_skill: LLMSkill,
    *,
    edited_content: dict[str, str] | None = None,
) -> None:
    """Carry files forward to the new version, optionally overriding content for specific paths."""
    source_files = list(LLMSkillFile.objects.filter(skill=source_skill))
    if not source_files:
        return
    overrides = edited_content or {}
    LLMSkillFile.objects.bulk_create(
        [
            LLMSkillFile(
                skill=target_skill,
                path=f.path,
                content=overrides.get(f.path, f.content),
                content_type=f.content_type,
            )
            for f in source_files
        ]
    )


def duplicate_skill(
    team: Team,
    *,
    user: User,
    source_name: str,
    new_name: str,
) -> LLMSkill:
    with transaction.atomic():
        source_latest = (
            LLMSkill.objects.select_for_update()
            .filter(team=team, name=source_name, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if source_latest is None:
            raise LLMSkillNotFoundError()

        if LLMSkill.objects.filter(team=team, name=new_name, deleted=False).exists():
            raise LLMSkillDuplicateNameConflictError()

        try:
            new_skill = LLMSkill.objects.create(
                team=team,
                name=new_name,
                description=source_latest.description,
                body=source_latest.body,
                license=source_latest.license,
                compatibility=source_latest.compatibility,
                allowed_tools=source_latest.allowed_tools,
                metadata=source_latest.metadata,
                version=1,
                is_latest=True,
                created_by=user,
            )
        except IntegrityError as err:
            if "unique_llm_skill_latest_per_team" in str(err) or "unique_llm_skill_version_per_team" in str(err):
                raise LLMSkillDuplicateNameConflictError() from err
            raise

        _copy_files(source_latest, new_skill)

    refreshed = get_active_skill_queryset(team).filter(pk=new_skill.pk).first()
    return refreshed if refreshed is not None else new_skill


def _select_latest_for_write(
    team: Team,
    skill_name: str,
    base_version: int | None,
) -> LLMSkill:
    current_latest = (
        LLMSkill.objects.select_for_update()
        .filter(team=team, name=skill_name, deleted=False, is_latest=True)
        .order_by("-version", "-created_at", "-id")
        .first()
    )
    if current_latest is None:
        raise LLMSkillNotFoundError()
    if base_version is not None and base_version != current_latest.version:
        raise LLMSkillVersionConflictError(current_version=current_latest.version)
    if current_latest.version >= MAX_SKILL_VERSION:
        raise LLMSkillVersionLimitError(max_version=MAX_SKILL_VERSION)
    return current_latest


def _create_next_version_with_files(
    team: Team,
    user: User,
    current_latest: LLMSkill,
    next_files: list[LLMSkillFile],
) -> LLMSkill:
    LLMSkill.objects.filter(pk=current_latest.pk).update(is_latest=False)
    next_skill = LLMSkill.objects.create(
        team=team,
        name=current_latest.name,
        description=current_latest.description,
        body=current_latest.body,
        license=current_latest.license,
        compatibility=current_latest.compatibility,
        allowed_tools=current_latest.allowed_tools,
        metadata=current_latest.metadata,
        version=current_latest.version + 1,
        is_latest=True,
        created_by=user,
    )
    if next_files:
        LLMSkillFile.objects.bulk_create(
            [
                LLMSkillFile(
                    skill=next_skill,
                    path=f.path,
                    content=f.content,
                    content_type=f.content_type,
                )
                for f in next_files
            ]
        )
    return next_skill


def _refresh_with_annotations(team: Team, skill: LLMSkill) -> LLMSkill:
    refreshed = get_active_skill_queryset(team).filter(pk=skill.pk).first()
    return refreshed if refreshed is not None else skill


def create_skill_file(
    team: Team,
    *,
    user: User,
    skill_name: str,
    path: str,
    content: str,
    content_type: str = "text/plain",
    base_version: int | None = None,
) -> LLMSkill:
    with transaction.atomic():
        current_latest = _select_latest_for_write(team, skill_name, base_version)
        existing_files = list(LLMSkillFile.objects.filter(skill=current_latest))
        if any(f.path == path for f in existing_files):
            raise LLMSkillFilePathConflictError(path=path)
        if len(existing_files) >= MAX_SKILL_FILE_COUNT:
            raise LLMSkillFileLimitError(max_count=MAX_SKILL_FILE_COUNT)

        next_files = [*existing_files, LLMSkillFile(path=path, content=content, content_type=content_type)]
        next_skill = _create_next_version_with_files(team, user, current_latest, next_files)

    return _refresh_with_annotations(team, next_skill)


def delete_skill_file(
    team: Team,
    *,
    user: User,
    skill_name: str,
    path: str,
    base_version: int | None = None,
) -> LLMSkill:
    with transaction.atomic():
        current_latest = _select_latest_for_write(team, skill_name, base_version)
        existing_files = list(LLMSkillFile.objects.filter(skill=current_latest))
        if not any(f.path == path for f in existing_files):
            raise LLMSkillFileNotFoundError(path=path)

        next_files = [f for f in existing_files if f.path != path]
        next_skill = _create_next_version_with_files(team, user, current_latest, next_files)

    return _refresh_with_annotations(team, next_skill)


def rename_skill_file(
    team: Team,
    *,
    user: User,
    skill_name: str,
    old_path: str,
    new_path: str,
    base_version: int | None = None,
) -> LLMSkill:
    with transaction.atomic():
        current_latest = _select_latest_for_write(team, skill_name, base_version)
        existing_files = list(LLMSkillFile.objects.filter(skill=current_latest))
        if not any(f.path == old_path for f in existing_files):
            raise LLMSkillFileNotFoundError(path=old_path)
        if any(f.path == new_path for f in existing_files):
            raise LLMSkillFilePathConflictError(path=new_path)

        next_files = [
            LLMSkillFile(
                path=new_path if f.path == old_path else f.path,
                content=f.content,
                content_type=f.content_type,
            )
            for f in existing_files
        ]
        next_skill = _create_next_version_with_files(team, user, current_latest, next_files)

    return _refresh_with_annotations(team, next_skill)


def archive_skill(team: Team, skill_name: str) -> list[int]:
    with transaction.atomic():
        skill_versions = list(
            LLMSkill.objects.select_for_update()
            .filter(team=team, name=skill_name, deleted=False)
            .order_by("version", "created_at", "id")
            .values_list("version", flat=True)
        )
        if not skill_versions:
            raise LLMSkillNotFoundError()
        LLMSkill.objects.filter(team=team, name=skill_name, deleted=False).update(
            deleted=True,
            is_latest=False,
        )
    return skill_versions
