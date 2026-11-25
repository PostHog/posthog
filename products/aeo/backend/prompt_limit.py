from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.facade.contracts import DEFAULT_MAX_ACTIVE_PROMPTS, PromptLimit, PromptLimitError
from products.aeo.backend.models import AEOPrompt, AEOTeamConfig


def active_prompt_count(team_id: int) -> int:
    return AEOPrompt.objects.for_team(team_id).using("default").filter(active=True, archived_at__isnull=True).count()


def max_active_prompts(team_id: int) -> int:
    limit = AEOTeamConfig.objects.for_team(team_id).values_list("max_active_prompts", flat=True).first()
    return DEFAULT_MAX_ACTIVE_PROMPTS if limit is None else limit


def read(team_id: int) -> PromptLimit:
    return PromptLimit(max_active_prompts=max_active_prompts(team_id), active_prompts=active_prompt_count(team_id))


def lock(team_id: int) -> PromptLimit:
    canonical = resolve_effective_team_id(team_id)
    config, _ = AEOTeamConfig.objects.for_team(canonical).select_for_update().get_or_create(team_id=canonical)
    return PromptLimit(max_active_prompts=config.max_active_prompts, active_prompts=active_prompt_count(canonical))


def check_room(limit: PromptLimit, adding: int) -> None:
    if adding > limit.remaining:
        raise PromptLimitError(limit, adding)


def set_max_active_prompts(team_id: int, max_active_prompts: int) -> PromptLimit:
    canonical = resolve_effective_team_id(team_id)
    AEOTeamConfig.objects.for_team(canonical).update_or_create(
        team_id=canonical, defaults={"max_active_prompts": max_active_prompts}
    )
    return read(canonical)
