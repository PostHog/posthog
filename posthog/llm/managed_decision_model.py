import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
import posthoganalytics

from posthog.models.team.team import Team
from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

DEFAULT_DECISION_MODEL = "posthog/hogference/jevk5-fp8-0.2"
PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60

logger = structlog.get_logger(__name__)


def get_app_prompt(prompt_name: str, *, label: str | None = None, version: int | None = None) -> dict[str, Any] | None:
    team = Team.objects.get_team_from_token(posthoganalytics.api_key)
    if team is None:
        return None
    return get_prompt_by_name_from_cache(team, prompt_name, version=version, label=label)


def model_from_config(config: Any, fallback: str = DEFAULT_DECISION_MODEL) -> str:
    model = config.get("model") if isinstance(config, dict) else None
    if isinstance(model, str) and 0 < len(model) <= 255 and not any(character.isspace() for character in model):
        return model
    return fallback


class ManagedDecisionModel:
    def __init__(self, prompt_name: str, fallback: str = DEFAULT_DECISION_MODEL) -> None:
        self.prompt_name = prompt_name
        self.fallback = fallback
        self._model = fallback
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decision-model-prompt")
        self._refreshed_at = float("-inf")
        self._refreshing = False

    def current(self) -> str:
        with self._lock:
            if not self._refreshing and time.monotonic() - self._refreshed_at >= PROMPT_REFRESH_SECONDS:
                self._refreshing = True
                self._executor.submit(self._refresh)
            return self._model

    def fetch(self, *, version: int | None = None) -> str:
        result = get_app_prompt(self.prompt_name, label=PROMPT_LABEL if version is None else None, version=version)
        if result is None:
            if version is not None:
                raise RuntimeError(f"Managed prompt {self.prompt_name} version {version} was not found")
            raise RuntimeError(f"Managed prompt {self.prompt_name} was not found")
        config = result.get("config")
        model = model_from_config(config, self.fallback)
        configured = config.get("model") if isinstance(config, dict) else None
        if configured is not None and model == self.fallback and configured != self.fallback:
            logger.warning("managed_decision_model_invalid", prompt_name=self.prompt_name)
        return model

    def _refresh(self) -> None:
        model = None
        try:
            model = self.fetch()
        except Exception:
            logger.exception("managed_decision_model_refresh_failed", prompt_name=self.prompt_name)
        with self._lock:
            if model is not None:
                self._model = model
            self._refreshed_at = time.monotonic()
            self._refreshing = False
