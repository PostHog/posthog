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

from products.ai_observability.backend.llm.errors import UnsupportedModelError
from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DECISIONS_BASE_URL = "https://openrouter.ai/api/alpha"

# For App Attribution
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://posthog.com",
    "X-Title": "PostHog",
}

# The default model list only has text-output models, so ask for every output modality.
OPENROUTER_ALL_MODELS_URL = f"{OPENROUTER_BASE_URL}/models?output_modalities=all"
# Older workers expect a non-chat-only snapshot, so use a separate cache namespace.
MODEL_MODALITIES_CACHE_KEY = "ai_observability:openrouter:model_output_modalities:v1"
MODEL_MODALITIES_LAST_GOOD_CACHE_KEY = f"{MODEL_MODALITIES_CACHE_KEY}:last_good"
MODEL_MODALITIES_CACHE_TTL_SECONDS = 60 * 60
MODEL_MODALITIES_FETCH_TIMEOUT_SECONDS = 5.0
# Short, so a catalogue outage adds the fetch timeout at most once a minute.
MODEL_MODALITIES_UNAVAILABLE_TTL_SECONDS = 60
_CATALOGUE_UNAVAILABLE = "unavailable"


def _model_output_modalities(*, refresh: bool = True) -> dict[str, list[str]] | None:
    """Output modalities of OpenRouter models.

    Returns the last successful catalogue during outages, or None before the first success.
    """
    cached = cache.get(MODEL_MODALITIES_CACHE_KEY)
    if cached == _CATALOGUE_UNAVAILABLE:
        return cache.get(MODEL_MODALITIES_LAST_GOOD_CACHE_KEY)
    if cached is not None:
        return cached
    if not refresh:
        return cache.get(MODEL_MODALITIES_LAST_GOOD_CACHE_KEY)
    try:
        response = httpx.get(OPENROUTER_ALL_MODELS_URL, timeout=MODEL_MODALITIES_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        models = response.json()["data"]
        modalities = {
            model["id"]: (model.get("architecture") or {}).get("output_modalities") or ["text"] for model in models
        }
    except Exception:
        logger.warning("Could not fetch the OpenRouter model catalogue", exc_info=True)
        cache.set(MODEL_MODALITIES_CACHE_KEY, _CATALOGUE_UNAVAILABLE, MODEL_MODALITIES_UNAVAILABLE_TTL_SECONDS)
        return cache.get(MODEL_MODALITIES_LAST_GOOD_CACHE_KEY)
    # An outage must not discard the last successful catalogue.
    cache.set(MODEL_MODALITIES_LAST_GOOD_CACHE_KEY, modalities, timeout=None)
    cache.set(MODEL_MODALITIES_CACHE_KEY, modalities, MODEL_MODALITIES_CACHE_TTL_SECONDS)
    return modalities


def non_chat_model_ids() -> frozenset[str] | None:
    models = _model_output_modalities()
    return (
        frozenset(model for model, modalities in models.items() if "text" not in modalities)
        if models is not None
        else None
    )


def decision_model_ids(*, refresh: bool = True, decision_only: bool = False) -> frozenset[str] | None:
    models = _model_output_modalities(refresh=refresh)
    return (
        frozenset(
            model
            for model, modalities in models.items()
            if "decisions" in modalities and (not decision_only or "text" not in modalities)
        )
        if models is not None
        else None
    )


def is_non_chat_model(model: str) -> bool:
    """True only when OpenRouter lists the model and says it cannot produce text."""
    ids = non_chat_model_ids()
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
        # Read the catalogue only on the failure path, so successful calls pay no extra latency.
        try:
            return super().complete(request, api_key, analytics, base_url=OPENROUTER_BASE_URL)
        except Exception as e:
            # A non-chat model fails in several shapes (a 400, a 404, unreadable output).
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
