from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.models.llm_prompt import LLMPrompt, annotate_llm_prompt_version_history_metadata
from posthog.storage.llm_prompt_cache import invalidate_prompt_latest_cache, invalidate_prompt_version_caches

SYNC_ARCHIVE_VERSION_INVALIDATION_LIMIT = 100
MAX_PROMPT_VERSION = 2000


class LLMPromptNotFoundError(Exception):
    pass


@dataclass
class LLMPromptVersionConflictError(Exception):
    current_version: int


@dataclass
class LLMPromptVersionLimitError(Exception):
    max_version: int


def get_active_prompt_queryset(team: Team) -> QuerySet[LLMPrompt]:
    return annotate_llm_prompt_version_history_metadata(
        LLMPrompt.objects.filter(team=team, deleted=False).select_related("created_by")
    )


def get_latest_prompts_queryset(team: Team) -> QuerySet[LLMPrompt]:
    return get_active_prompt_queryset(team).filter(is_latest=True)


def get_prompt_by_name_from_db(
    team: Team,
    prompt_name: str,
    version: int | None = None,
    version_id: str | None = None,
) -> LLMPrompt | None:
    queryset = get_active_prompt_queryset(team).filter(name=prompt_name)

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
    prompt_name: str,
    *,
    limit: int,
    offset: int | None = None,
    before_version: int | None = None,
) -> tuple[list[LLMPrompt], bool]:
    queryset = (
        LLMPrompt.objects.filter(team=team, name=prompt_name, deleted=False)
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


def publish_prompt_version(
    team: Team,
    *,
    user: User,
    prompt_name: str,
    prompt_payload: Any,
    base_version: int,
) -> LLMPrompt:
    with transaction.atomic():
        current_latest = (
            LLMPrompt.objects.select_for_update()
            .filter(team=team, name=prompt_name, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if current_latest is None:
            raise LLMPromptNotFoundError()

        if base_version != current_latest.version:
            raise LLMPromptVersionConflictError(current_version=current_latest.version)
        if current_latest.version >= MAX_PROMPT_VERSION:
            raise LLMPromptVersionLimitError(max_version=MAX_PROMPT_VERSION)

        LLMPrompt.objects.filter(pk=current_latest.pk).update(is_latest=False)
        published_prompt = LLMPrompt.objects.create(
            team=team,
            name=current_latest.name,
            prompt=prompt_payload,
            version=current_latest.version + 1,
            is_latest=True,
            created_by=user,
        )

        refreshed_prompt = (
            get_active_prompt_queryset(team).filter(pk=published_prompt.pk).order_by("-created_at", "-id").first()
        )
        if refreshed_prompt is not None:
            return refreshed_prompt

        fallback_prompt = (
            annotate_llm_prompt_version_history_metadata(
                LLMPrompt.objects.filter(team=team, deleted=False).select_related("created_by")
            )
            .filter(pk=published_prompt.pk)
            .order_by("-created_at", "-id")
            .first()
        )
        return fallback_prompt if fallback_prompt is not None else published_prompt


class LLMPromptDuplicateNameConflictError(Exception):
    pass


def duplicate_prompt(
    team: Team,
    *,
    user: User,
    source_name: str,
    new_name: str,
) -> LLMPrompt:
    with transaction.atomic():
        source_latest = (
            LLMPrompt.objects.select_for_update()
            .filter(team=team, name=source_name, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if source_latest is None:
            raise LLMPromptNotFoundError()

        if LLMPrompt.objects.filter(team=team, name=new_name, deleted=False).exists():
            raise LLMPromptDuplicateNameConflictError()

        try:
            new_prompt = LLMPrompt.objects.create(
                team=team,
                name=new_name,
                prompt=source_latest.prompt,
                version=1,
                is_latest=True,
                created_by=user,
            )
        except IntegrityError as err:
            if "unique_llm_prompt_latest_per_team" in str(err) or "unique_llm_prompt_version_per_team" in str(err):
                raise LLMPromptDuplicateNameConflictError() from err
            raise

    refreshed = get_active_prompt_queryset(team).filter(pk=new_prompt.pk).first()
    return refreshed if refreshed is not None else new_prompt


def archive_prompt(team: Team, prompt_name: str) -> list[int]:
    with transaction.atomic():
        prompt_versions = list(
            LLMPrompt.objects.select_for_update()
            .filter(team=team, name=prompt_name, deleted=False)
            .order_by("version", "created_at", "id")
            .values_list("version", flat=True)
        )
        if not prompt_versions:
            raise LLMPromptNotFoundError()
        LLMPrompt.objects.filter(team=team, name=prompt_name, deleted=False).update(
            deleted=True,
            is_latest=False,
        )

        def invalidate_caches_on_commit() -> None:
            invalidate_prompt_latest_cache(team.id, prompt_name)

            sync_versions = (
                prompt_versions if settings.TEST else prompt_versions[:SYNC_ARCHIVE_VERSION_INVALIDATION_LIMIT]
            )
            invalidate_prompt_version_caches(team.id, prompt_name, sync_versions)

            remaining_versions = prompt_versions[len(sync_versions) :]
            if not remaining_versions:
                return

            try:
                from posthog.tasks.llm_prompt_cache import invalidate_archived_prompt_versions_cache_task

                invalidate_archived_prompt_versions_cache_task.delay(
                    team.id,
                    prompt_name,
                    remaining_versions[0],
                    remaining_versions[-1],
                )
            except Exception as err:
                capture_exception(err)
                invalidate_prompt_version_caches(team.id, prompt_name, remaining_versions)

        transaction.on_commit(invalidate_caches_on_commit)

    return prompt_versions
