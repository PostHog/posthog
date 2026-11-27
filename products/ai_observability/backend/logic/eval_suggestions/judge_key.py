from django.db.models import F

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


def judge_key(team_id: int) -> LLMProviderKey | None:
    """The working key a suggested judge runs on: the team's most recently used one whose provider has a default model."""
    return (
        LLMProviderKey.objects.filter(
            team_id=team_id, state=LLMProviderKey.State.OK, provider__in=list(DEFAULT_MODEL_BY_PROVIDER)
        )
        .order_by(F("last_used_at").desc(nulls_last=True), "-created_at")
        .first()
    )
