import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
import posthoganalytics
from posthoganalytics.ai.prompts import Prompts

DEFAULT_DECISION_MODEL = "posthog/hogference/jevk5-fp8-0.2"
PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60
PROMPT_CACHE_SECONDS = 5 * 60

logger = structlog.get_logger(__name__)


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
        self._prompts_lock = threading.Lock()
        self._prompts: Prompts | None = None
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
        if not posthoganalytics.personal_api_key:
            if version is not None:
                raise RuntimeError(f"Managed prompt version {version} requires POSTHOG_PERSONAL_API_KEY")
            if self._prompts is not None:
                raise RuntimeError("Managed prompt key is no longer available")
            return self.fallback
        with self._prompts_lock:
            if self._prompts is None:
                self._prompts = Prompts(
                    posthoganalytics, capture_errors=True, default_cache_ttl_seconds=PROMPT_CACHE_SECONDS
                )
            result = self._prompts.get(
                self.prompt_name,
                with_metadata=True,
                label=PROMPT_LABEL if version is None else None,
                version=version,
            )
        if result.source == "code_fallback":
            raise RuntimeError(f"Managed prompt {self.prompt_name} returned a code fallback")
        model = model_from_config(result.config, self.fallback)
        configured = result.config.get("model") if isinstance(result.config, dict) else None
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
