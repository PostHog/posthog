"""DeepSeek provider for the unified LLM client.

DeepSeek exposes an OpenAI-compatible API and is BYOKEY-only.
"""

import logging
from collections.abc import Generator
from typing import Any

import openai

from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekAdapter(OpenAIAdapter):
    """DeepSeek provider that reuses OpenAI's completion/streaming logic."""

    name = "deepseek"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=DEEPSEEK_BASE_URL)

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk]:
        yield from super().stream(request, api_key, analytics, base_url=DEEPSEEK_BASE_URL)

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate a DeepSeek API key using a models list request."""
        from products.ai_observability.backend.models.provider_keys import LLMProviderKey

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to DeepSeek")
        except Exception:
            logger.exception("DeepSeek key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available DeepSeek models. Returns empty list without a key (BYOKEY-only)."""
        if not api_key:
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            # DeepSeek's models endpoint omits a `created` timestamp, so sort by id for stable output.
            return [m.id for m in sorted(client.models.list(), key=lambda m: m.id)]
        except Exception:
            logger.exception("Error listing DeepSeek models")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("DeepSeek is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("DeepSeek is BYOKEY-only. No default API key is available.")
