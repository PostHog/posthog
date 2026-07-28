from collections.abc import Iterable
from typing import Any, cast

from django.conf import settings
from django.db.models import QuerySet

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType
from posthog.storage.llm_prompt_cache_keys import (
    parse_prompt_cache_key,
    prompt_label_cache_key,
    prompt_latest_cache_key,
    prompt_version_cache_key,
)
from posthog.storage.llm_prompt_cache_payloads import (
    INTERNAL_FIRST_VERSION_ID_KEY,
    is_stale_exact_version_entry,
    merge_prompt_version_history_metadata,
    serialize_prompt,
    serialize_prompt_version,
    strip_internal_metadata,
)

from products.ai_observability.backend.models.llm_prompt import (
    LLMPrompt,
    LLMPromptLabel,
    annotate_llm_prompt_version_history_metadata,
)

# Used in tests; keep as module export.
_serialize_prompt = serialize_prompt


def _get_active_prompt_queryset_for_team_id(team_id: int) -> QuerySet[LLMPrompt]:
    return annotate_llm_prompt_version_history_metadata(LLMPrompt.objects.filter(team_id=team_id, deleted=False))


def _attach_first_version_id(prompt: LLMPrompt, team_id: int, prompt_name: str) -> LLMPrompt:
    prompt_with_first_version_id = cast(Any, prompt)
    if prompt.version == 1:
        prompt_with_first_version_id.first_version_id = prompt.id
        return prompt

    first_version_id = (
        LLMPrompt.objects.filter(team_id=team_id, name=prompt_name, deleted=False, version=1)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
        .first()
    )
    if first_version_id is not None:
        prompt_with_first_version_id.first_version_id = first_version_id
    return prompt


def _get_latest_prompt_from_db(team_id: int, prompt_name: str) -> LLMPrompt | None:
    return (
        _get_active_prompt_queryset_for_team_id(team_id)
        .filter(name=prompt_name, is_latest=True)
        .order_by("-version", "-created_at", "-id")
        .first()
    )


def _get_prompt_version_from_db(team_id: int, prompt_name: str, version: int) -> LLMPrompt | None:
    prompt = (
        LLMPrompt.objects.filter(team_id=team_id, deleted=False)
        .filter(name=prompt_name, version=version)
        .order_by("created_at", "id")
        .first()
    )
    if prompt is None:
        return None
    return _attach_first_version_id(prompt, team_id, prompt_name)


def _get_labeled_prompt_from_db(team_id: int, prompt_name: str, label_name: str) -> LLMPrompt | None:
    label = (
        LLMPromptLabel.objects.filter(team_id=team_id, prompt_name=prompt_name, name=label_name)
        .select_related("prompt")
        .first()
    )
    if label is None or label.prompt.deleted:
        return None
    return _attach_first_version_id(label.prompt, team_id, prompt_name)


def _serialize_labeled_prompt(prompt: LLMPrompt, label_name: str) -> dict[str, Any]:
    return {**serialize_prompt_version(prompt, include_internal=True), "label": label_name}


def _load_prompt_cache(cache_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    parsed_key = parse_prompt_cache_key(cache_key)
    if parsed_key is None:
        return HyperCacheStoreMissing()

    team_id, prompt_name, version, label_name = parsed_key

    if label_name is not None:
        labeled_prompt = _get_labeled_prompt_from_db(team_id, prompt_name, label_name)
        if labeled_prompt is None:
            return HyperCacheStoreMissing()
        return _serialize_labeled_prompt(labeled_prompt, label_name)

    if version is None:
        prompt = _get_latest_prompt_from_db(team_id, prompt_name)
        if prompt is None:
            return HyperCacheStoreMissing()
        return serialize_prompt(prompt, include_internal=True)

    prompt = _get_prompt_version_from_db(team_id, prompt_name, version)
    if prompt is None:
        return HyperCacheStoreMissing()

    return serialize_prompt_version(prompt, include_internal=True)


llm_prompts_hypercache = HyperCache(
    namespace="llm_prompts",
    value="prompt.json",
    load_fn=_load_prompt_cache,
    cache_ttl=settings.LLM_PROMPTS_CACHE_TTL,
    cache_miss_ttl=settings.LLM_PROMPTS_CACHE_MISS_TTL,
)

# Label entries go through their own instance (same key space) with a short TTL. Latest
# and version entries hold immutable content, but a label entry is a resolved pointer:
# a cache fill racing an invalidation can store an already-stale resolution that the
# generation marker cannot detect. The short TTL bounds that staleness to a minute;
# signal invalidation still makes the common path near-instant. The S3 tier is disabled
# entirely — an S3 copy has no TTL, so a stale fill there would keep restoring itself
# past every redis expiry, and reads would pay a guaranteed-miss S3 round-trip.
llm_prompts_label_hypercache = HyperCache(
    namespace="llm_prompts",
    value="prompt.json",
    load_fn=_load_prompt_cache,
    cache_ttl=settings.LLM_PROMPTS_LABEL_CACHE_TTL,
    cache_miss_ttl=settings.LLM_PROMPTS_LABEL_CACHE_TTL,
    s3_enabled=False,
)


def get_prompt_by_name_from_cache(
    team: Team,
    prompt_name: str,
    version: int | None = None,
    label: str | None = None,
) -> dict[str, Any] | None:
    latest_key = prompt_latest_cache_key(team.id, prompt_name)
    latest_prompt = llm_prompts_hypercache.get_from_cache(latest_key)

    if not isinstance(latest_prompt, dict) or not isinstance(latest_prompt.get(INTERNAL_FIRST_VERSION_ID_KEY), str):
        db_latest = _get_latest_prompt_from_db(team.id, prompt_name)
        if db_latest is None:
            return None

        latest_prompt = serialize_prompt(db_latest, include_internal=True)
        try:
            llm_prompts_hypercache.set_cache_value(latest_key, latest_prompt)
        except Exception as err:
            capture_exception(err)

    if label is not None:
        label_key = prompt_label_cache_key(team.id, prompt_name, label)
        labeled_prompt = llm_prompts_label_hypercache.get_from_cache(label_key)
        if not isinstance(labeled_prompt, dict):
            return None

        # The generation marker guards against a stale entry surviving an archive + recreate
        # of the whole prompt; label moves are covered by the model-signal invalidation.
        if is_stale_exact_version_entry(labeled_prompt, latest_prompt):
            try:
                invalidate_prompt_label_cache(team.id, prompt_name, label)
            except Exception as err:
                capture_exception(err)

            db_labeled = _get_labeled_prompt_from_db(team.id, prompt_name, label)
            if db_labeled is None:
                return None
            labeled_prompt = _serialize_labeled_prompt(db_labeled, label)
            try:
                llm_prompts_label_hypercache.set_cache_value(label_key, labeled_prompt)
            except Exception as err:
                capture_exception(err)

        return strip_internal_metadata(merge_prompt_version_history_metadata(labeled_prompt, latest_prompt))

    if version is None or version == latest_prompt["latest_version"]:
        return strip_internal_metadata(latest_prompt)

    version_key = prompt_version_cache_key(team.id, prompt_name, version)
    exact_prompt = llm_prompts_hypercache.get_from_cache(version_key)
    if not isinstance(exact_prompt, dict):
        return None

    if is_stale_exact_version_entry(exact_prompt, latest_prompt):
        try:
            invalidate_prompt_version_cache(team.id, prompt_name, version)
        except Exception as err:
            capture_exception(err)

        db_prompt = _get_prompt_version_from_db(team.id, prompt_name, version)
        if db_prompt is None:
            return None
        exact_prompt = serialize_prompt_version(db_prompt, include_internal=True)
        try:
            llm_prompts_hypercache.set_cache_value(version_key, exact_prompt)
        except Exception as err:
            capture_exception(err)

    return strip_internal_metadata(merge_prompt_version_history_metadata(exact_prompt, latest_prompt))


def invalidate_prompt_latest_cache(team: Team | str | int, prompt_name: str) -> None:
    llm_prompts_hypercache.clear_cache(prompt_latest_cache_key(team, prompt_name))


def invalidate_prompt_version_cache(team: Team | str | int, prompt_name: str, version: int) -> None:
    llm_prompts_hypercache.clear_cache(prompt_version_cache_key(team, prompt_name, version))


def invalidate_prompt_label_cache(team: Team | str | int, prompt_name: str, label_name: str) -> None:
    llm_prompts_label_hypercache.clear_cache(prompt_label_cache_key(team, prompt_name, label_name))


def invalidate_prompt_version_caches(team: Team | str | int, prompt_name: str, versions: Iterable[int]) -> None:
    for version in versions:
        invalidate_prompt_version_cache(team, prompt_name, int(version))


def invalidate_prompt_version_cache_range(team: Team | str | int, prompt_name: str, start: int, end: int) -> None:
    if start > end:
        return
    for version in range(start, end + 1):
        invalidate_prompt_version_cache(team, prompt_name, version)


def invalidate_prompt_name_caches(team: Team | str | int, prompt_name: str, versions: list[int]) -> None:
    invalidate_prompt_latest_cache(team, prompt_name)
    invalidate_prompt_version_caches(team, prompt_name, versions)
