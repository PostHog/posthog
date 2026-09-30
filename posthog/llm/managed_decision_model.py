import threading
from typing import Any

from django.conf import settings

import structlog
from cachetools import TTLCache, cached
from posthoganalytics.ai.prompts import PromptResult

DEFAULT_DECISION_MODEL = "posthog/hogference/jevk5-fp8-0.2"
PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60

logger = structlog.get_logger(__name__)

# Only US cloud has PostHog's own prompts here; on EU and self-hosted, team 2 belongs to someone else.
POSTHOG_PROMPTS_TEAM_ID = 2

APP_PROMPT_CACHE: TTLCache = TTLCache(maxsize=64, ttl=PROMPT_REFRESH_SECONDS)


@cached(APP_PROMPT_CACHE, lock=threading.Lock())
def get_app_prompt(prompt_name: str, *, version: int | None = None) -> PromptResult | None:
    """The `production` version, or `version` when given. None outside US cloud."""
    if (settings.CLOUD_DEPLOYMENT or "").upper() != "US":
        return None

    from posthog.models import Team
    from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

    # The cache helper only reads team.id, so an unsaved instance saves a query per lookup.
    team = Team(id=POSTHOG_PROMPTS_TEAM_ID)
    label = PROMPT_LABEL if version is None else None
    serialized = get_prompt_by_name_from_cache(team, prompt_name, version=version, label=label)
    if serialized is None:
        return None
    return PromptResult(
        source="api",
        prompt=serialized.get("prompt") or "",
        name=prompt_name,
        version=serialized.get("version"),
        label=serialized.get("label"),
        config=serialized.get("config"),
    )


def model_from_config(config: Any, fallback: str = DEFAULT_DECISION_MODEL) -> str:
    model = config.get("model") if isinstance(config, dict) else None
    if isinstance(model, str) and 0 < len(model) <= 255 and not any(character.isspace() for character in model):
        return model
    return fallback


class ManagedDecisionModel:
    def __init__(self, prompt_name: str, fallback: str = DEFAULT_DECISION_MODEL) -> None:
        self.prompt_name = prompt_name
        self.fallback = fallback

    def fetch(self, *, version: int | None = None) -> str:
        result = get_app_prompt(self.prompt_name, version=version)
        if result is None:
            return self.fallback
        config = result.config
        model = model_from_config(config, self.fallback)
        configured = config.get("model") if isinstance(config, dict) else None
        if configured is not None and model == self.fallback and configured != self.fallback:
            logger.warning("managed_decision_model_invalid", prompt_name=self.prompt_name)
        return model
