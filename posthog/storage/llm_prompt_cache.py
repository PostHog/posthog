from typing import Any

from django.conf import settings

from posthog.exceptions_capture import capture_exception
from posthog.models.llm_prompt import LLMPrompt
from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType


def _serialize_prompt(prompt: LLMPrompt) -> dict[str, Any]:
    return {
        "id": str(prompt.id),
        "name": prompt.name,
        "prompt": prompt.prompt,
        "version": prompt.version,
        "created_at": prompt.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": prompt.updated_at.isoformat().replace("+00:00", "Z"),
        "deleted": prompt.deleted,
    }


def _load_team_prompts_by_name_cache(team_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    try:
        team = HyperCache.team_from_key(team_key)
    except Team.DoesNotExist:
        return HyperCacheStoreMissing()

    prompts = LLMPrompt.objects.filter(team=team, deleted=False).order_by("created_at", "id")
    prompts_by_name = {prompt.name: _serialize_prompt(prompt) for prompt in prompts}
    return {"prompts_by_name": prompts_by_name}


llm_prompts_hypercache = HyperCache(
    namespace="llm_prompts",
    value="prompts_by_name.json",
    load_fn=_load_team_prompts_by_name_cache,
    cache_ttl=settings.LLM_PROMPTS_CACHE_TTL,
    cache_miss_ttl=settings.LLM_PROMPTS_CACHE_MISS_TTL,
)


def get_prompt_by_name_from_cache(team: Team, prompt_name: str) -> dict[str, Any] | None:
    team_prompts = llm_prompts_hypercache.get_from_cache(team)
    if not team_prompts:
        return None

    prompts_by_name = team_prompts.get("prompts_by_name", {})
    prompt = prompts_by_name.get(prompt_name)
    if isinstance(prompt, dict):
        return prompt

    db_prompt = (
        LLMPrompt.objects.filter(team=team, name=prompt_name, deleted=False).order_by("created_at", "id").first()
    )
    if db_prompt is None:
        return None

    # Stale map protection: if DB has the prompt but cache map missed it,
    # invalidate the team map so subsequent reads use a fresh cache state.
    try:
        invalidate_team_prompt_cache(team.id)
    except Exception as err:
        capture_exception(err)

    return _serialize_prompt(db_prompt)


def invalidate_team_prompt_cache(team: Team | str | int) -> None:
    llm_prompts_hypercache.clear_cache(team)
