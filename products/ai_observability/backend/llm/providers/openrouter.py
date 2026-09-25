"""OpenRouter provider for unified LLM client.

OpenRouter is an LLM gateway with an OpenAI-compatible API that exposes models
from many providers. It is BYOKEY-only (no PostHog-funded key).
"""

import logging
from collections.abc import Generator
from typing import Any

from django.core.cache import cache

import httpx
import openai

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ProviderConnectionError,
    QuotaExceededError,
    RateLimitError,
    UnsupportedModelError,
)
from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# For App Attribution
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://posthog.com",
    "X-Title": "PostHog",
}

# The default model list only has text-output models, so ask for every output modality.
OPENROUTER_ALL_MODELS_URL = f"{OPENROUTER_BASE_URL}/models?output_modalities=all"
NON_CHAT_MODELS_CACHE_KEY = "ai_observability:openrouter:non_chat_models"
NON_CHAT_MODELS_CACHE_TTL_SECONDS = 60 * 60
NON_CHAT_MODELS_FETCH_TIMEOUT_SECONDS = 5.0

# These failures are about the key or the network, not about the model.
_KEY_OR_NETWORK_ERRORS = (AuthenticationError, QuotaExceededError, RateLimitError, ProviderConnectionError)


def _non_chat_model_ids() -> frozenset[str] | None:
    """IDs of OpenRouter models that cannot produce text, such as decision models.

    Returns None when the catalogue is unavailable, so callers fail open.
    """
    cached = cache.get(NON_CHAT_MODELS_CACHE_KEY)
    if cached is not None:
        return frozenset(cached)
    try:
        response = httpx.get(OPENROUTER_ALL_MODELS_URL, timeout=NON_CHAT_MODELS_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        models = response.json()["data"]
        ids = sorted(
            model["id"]
            for model in models
            if "text" not in (model.get("architecture") or {}).get("output_modalities", ["text"])
        )
    except Exception:
        logger.warning("Could not fetch the OpenRouter model catalogue", exc_info=True)
        return None
    cache.set(NON_CHAT_MODELS_CACHE_KEY, ids, NON_CHAT_MODELS_CACHE_TTL_SECONDS)
    return frozenset(ids)


def is_non_chat_model(model: str) -> bool:
    """True only when OpenRouter lists the model and says it cannot produce text."""
    ids = _non_chat_model_ids()
    return ids is not None and model in ids


class OpenRouterAdapter(OpenAIAdapter):
    """OpenRouter provider that reuses OpenAI's completion/streaming logic."""

    name = "openrouter"

    def _get_default_headers(self) -> dict[str, str]:
        return OPENROUTER_HEADERS

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        try:
            return super().complete(request, api_key, analytics, base_url=OPENROUTER_BASE_URL)
        except _KEY_OR_NETWORK_ERRORS:
            raise
        except Exception as e:
            # A non-chat model fails in different ways (a 400, a 404, or unreadable output).
            # The catalogue gives one answer for all of them.
            if is_non_chat_model(request.model):
                raise UnsupportedModelError(request.model) from e
            raise

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk]:
        yield from super().stream(request, api_key, analytics, base_url=OPENROUTER_BASE_URL)

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an OpenRouter API key using the auth/key endpoint."""
        from products.ai_observability.backend.models.provider_keys import LLMProviderKey

        try:
            response = httpx.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=OpenAIConfig.TIMEOUT,
            )

            if response.status_code == 200:
                return (LLMProviderKey.State.OK, None)

            if response.status_code == 401:
                return (LLMProviderKey.State.INVALID, "Invalid API key")

            return (LLMProviderKey.State.ERROR, f"Unexpected response status: {response.status_code}")

        except httpx.TimeoutException:
            return (LLMProviderKey.State.ERROR, "Request timed out, please try again")
        except httpx.ConnectError:
            return (LLMProviderKey.State.ERROR, "Could not connect to OpenRouter")
        except Exception as e:
            logger.exception(f"OpenRouter key validation error: {e}")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available OpenRouter models. Returns empty list without a key (BYOKEY-only)."""
        if not api_key:
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
                default_headers=OPENROUTER_HEADERS,
            )
            return [m.id for m in sorted(client.models.list(), key=lambda m: m.created, reverse=True)]
        except Exception:
            logger.exception("Error listing OpenRouter models")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("OpenRouter is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("OpenRouter is BYOKEY-only. No default API key is available.")
