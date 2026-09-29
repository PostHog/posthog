import time
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
import posthoganalytics
from posthoganalytics.ai.prompts import PromptResult, Prompts

DEFAULT_DECISION_MODEL = "posthog/hogference/jevk5-fp8-0.2"
PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60

logger = structlog.get_logger(__name__)


@functools.cache
def app_prompts() -> Prompts:
    # PostHog's own prompts live in the US project, and EU has no copy of that project, so every region
    # reads them through the SDK. One client per process keeps the SDK cache between refreshes.
    # It is built on first use, because apps.ready() sets the key after this module can be imported.
    return Prompts(posthoganalytics, capture_errors=True)


def get_app_prompt(prompt_name: str, *, label: str | None = None, version: int | None = None) -> PromptResult | None:
    # Without a key (tests, local dev, self-hosted) the SDK still sends the request and gets a 401.
    if not posthoganalytics.personal_api_key:
        return None
    return app_prompts().get(prompt_name, with_metadata=True, label=label, version=version)


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
        config = result.config
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
