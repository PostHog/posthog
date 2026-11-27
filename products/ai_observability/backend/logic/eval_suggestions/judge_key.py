from django.db.models import Count, Q

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


def provider_for_model(model: str) -> str | None:
    return next((provider for provider, default in DEFAULT_MODEL_BY_PROVIDER.items() if default == model), None)


def judge_key(team_id: int, provider: str | None = None, user_id: int | None = None) -> LLMProviderKey | None:
    """The key a suggested judge runs on: the working key most of the team's judges use, else the newest.

    Only keys that run their provider's default model directly qualify, so custom endpoints such as Azure
    Foundry deployments are left out. With a provider, a key for that provider wins over any other. With a user,
    only keys shared with the project or added by that user qualify, admins included, so an accept never
    starts billing a member's own account on someone else's behalf.
    """
    candidates = LLMProviderKey.objects.filter(
        team_id=team_id, state=LLMProviderKey.State.OK, provider__in=list(DEFAULT_MODEL_BY_PROVIDER)
    )
    if user_id is not None:
        candidates = candidates.filter(Q(shared=True) | Q(created_by_id=user_id))
    keys = [
        key
        for key in candidates.annotate(
            judges=Count(
                "model_configurations__evaluations", filter=Q(model_configurations__evaluations__deleted=False)
            )
        ).order_by("-judges", "-created_at")
        if not key.encrypted_config.get("azure_endpoint") and not key.encrypted_config.get("base_url")
    ]
    return next((key for key in keys if key.provider == provider), keys[0] if keys else None)
