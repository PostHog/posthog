import json
import difflib
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
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


def _prompt_to_text(prompt_payload: Any) -> str:
    """Normalize a prompt payload to a text representation for diffing."""
    if isinstance(prompt_payload, str):
        return prompt_payload
    return json.dumps(prompt_payload, indent=2, ensure_ascii=False)


@dataclass
class PromptCompareResult:
    version_from: LLMPrompt
    version_to: LLMPrompt
    diff: str
    additions: int
    deletions: int


def compare_prompt_versions(
    team: Team,
    prompt_name: str,
    *,
    version_from: int,
    version_to: int,
) -> PromptCompareResult:
    queryset = LLMPrompt.objects.filter(team=team, name=prompt_name, deleted=False).select_related("created_by")

    prompt_from = queryset.filter(version=version_from).first()
    if prompt_from is None:
        raise LLMPromptNotFoundError()

    prompt_to = queryset.filter(version=version_to).first()
    if prompt_to is None:
        raise LLMPromptNotFoundError()

    text_from = _prompt_to_text(prompt_from.prompt)
    text_to = _prompt_to_text(prompt_to.prompt)

    diff_lines = list(
        difflib.unified_diff(
            text_from.splitlines(),
            text_to.splitlines(),
            fromfile=f"v{version_from}",
            tofile=f"v{version_to}",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines)

    # Skip the two header lines (--- fromfile / +++ tofile) so we don't
    # mis-count content that happens to start with those prefixes.
    change_lines = diff_lines[2:] if len(diff_lines) >= 2 else []
    additions = sum(1 for line in change_lines if line.startswith("+"))
    deletions = sum(1 for line in change_lines if line.startswith("-"))

    return PromptCompareResult(
        version_from=prompt_from,
        version_to=prompt_to,
        diff=diff_text,
        additions=additions,
        deletions=deletions,
    )


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
