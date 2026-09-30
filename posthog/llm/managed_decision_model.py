import time
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.conf import settings

import structlog
from posthoganalytics.ai.prompts import PromptResult

DEFAULT_DECISION_MODEL = "posthog/hogference/jevk5-fp8-0.2"
PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60

logger = structlog.get_logger(__name__)

# PostHog's own prompts live in this project on US cloud. EU and self-hosted have no copy of it,
# and project 2 there belongs to someone else, so callers keep their bundled copy.
POSTHOG_PROMPTS_TEAM_ID = 2


def get_app_prompt(prompt_name: str, *, version: int | None = None) -> PromptResult | None:
    """The `production` version, or `version` when given. None outside US cloud."""
    if (settings.CLOUD_DEPLOYMENT or "").upper() != "US":
        return None

    from posthog.models import Team
    from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

    # Unsaved instance: the cache helper below only reads team.id, so this avoids a query per lookup.
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


class BackgroundRefresher[T]:
    # The SDK fetch blocks for up to 10 s on a cache miss and the pickers' budget is 2 s, so a request
    # reads the last value it has and at most one background fetch replaces it.
    def __init__(self, prompt_name: str, initial: T, fetch: Callable[[], T]) -> None:
        self._prompt_name = prompt_name
        self._fetch = fetch
        self._value = initial
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"refresh-{prompt_name}")
        self._refreshed_at = float("-inf")
        self._refreshing = False

    def current(self) -> T:
        with self._lock:
            if not self._refreshing and time.monotonic() - self._refreshed_at >= PROMPT_REFRESH_SECONDS:
                self._refreshing = True
                self._executor.submit(self._refresh)
            return self._value

    def _refresh(self) -> None:
        value: T | None = None
        try:
            value = self._fetch()
        except Exception:
            logger.exception("managed_prompt_refresh_failed", prompt_name=self._prompt_name)
        with self._lock:
            if value is not None:
                self._value = value
            self._refreshed_at = time.monotonic()
            self._refreshing = False


def model_from_config(config: Any, fallback: str = DEFAULT_DECISION_MODEL) -> str:
    model = config.get("model") if isinstance(config, dict) else None
    if isinstance(model, str) and 0 < len(model) <= 255 and not any(character.isspace() for character in model):
        return model
    return fallback


class ManagedDecisionModel:
    def __init__(self, prompt_name: str, fallback: str = DEFAULT_DECISION_MODEL) -> None:
        self.prompt_name = prompt_name
        self.fallback = fallback
        self._refresher = BackgroundRefresher(prompt_name, fallback, self.fetch)

    def current(self) -> str:
        return self._refresher.current()

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
