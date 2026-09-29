import time
import functools
import threading
from collections.abc import Callable
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
    # reads them through the SDK. One client per process keeps the last good copy when a fetch fails.
    # It is built on first use, because apps.ready() sets the key after this module can be imported.
    # A zero TTL leaves the refresh interval to BackgroundRefresher alone.
    return Prompts(posthoganalytics, capture_errors=True, default_cache_ttl_seconds=0)


def get_app_prompt(prompt_name: str, *, version: int | None = None) -> PromptResult | None:
    """The `production` version, or `version` when given. None without a personal API key."""
    # Without a key (tests, local dev, self-hosted) the SDK still sends the request and gets a 401.
    if not posthoganalytics.personal_api_key:
        if version is not None:
            raise RuntimeError(f"Reading {prompt_name} version {version} needs POSTHOG_PERSONAL_API_KEY")
        return None
    label = PROMPT_LABEL if version is None else None
    return app_prompts().get(prompt_name, with_metadata=True, label=label, version=version)


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
