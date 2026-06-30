"""Shared adapter for OpenAI-compatible BYOK providers."""

import logging
from collections.abc import Generator
from typing import Any, ClassVar

import openai

from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleByokAdapter(OpenAIAdapter):
    """Base for providers with OpenAI-compatible APIs and no PostHog trial key."""

    BASE_URL: ClassVar[str]
    PROVIDER_DISPLAY_NAME: ClassVar[str]

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=self.BASE_URL)

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk]:
        yield from super().stream(request, api_key, analytics, base_url=self.BASE_URL)

    @classmethod
    def validate_key(cls, api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        from products.ai_observability.backend.models.provider_keys import LLMProviderKey

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=cls.BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, f"Could not connect to {cls.PROVIDER_DISPLAY_NAME}")
        except Exception:
            logger.exception("%s key validation error", cls.PROVIDER_DISPLAY_NAME)
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @classmethod
    def list_models(cls, api_key: str | None = None, **kwargs: Any) -> list[str]:
        if not api_key:
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=cls.BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            return [m.id for m in sorted(client.models.list(), key=lambda m: m.created, reverse=True)]
        except Exception:
            logger.exception("Error listing %s models", cls.PROVIDER_DISPLAY_NAME)
            return []

    @classmethod
    def get_api_key(cls) -> str:
        raise ValueError(f"{cls.PROVIDER_DISPLAY_NAME} is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError(f"{self.PROVIDER_DISPLAY_NAME} is BYOKEY-only. No default API key is available.")
