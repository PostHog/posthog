"""
Unified LLM client for llm_analytics.

Provides a single entry point for all LLMA-internal LLM API calls.
"""

import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from products.ai_observability.backend.llm.errors import ProviderMismatchError, UnsupportedProviderError
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

if TYPE_CHECKING:
    from products.ai_observability.backend.llm.config import ProviderConfig
    from products.ai_observability.backend.llm.providers.base import Provider
    from products.ai_observability.backend.models.provider_keys import LLMProviderKey


# Some provider keys serve models that the model registry tags under a different
# provider. Azure OpenAI hosts the same models (gpt-4.1, ...) that the registry
# labels "openai", so a request built from that registry arrives with
# provider="openai" even though the key is "azure_openai". Map a key provider to
# the request providers it may legitimately serve so those requests validate and
# route through the key's provider instead of being rejected.
_COMPATIBLE_REQUEST_PROVIDERS: dict[str, frozenset[str]] = {
    "azure_openai": frozenset({"openai"}),
}


def _providers_compatible(key_provider: str, request_provider: str) -> bool:
    return key_provider == request_provider or request_provider in _COMPATIBLE_REQUEST_PROVIDERS.get(
        key_provider, frozenset()
    )


class Client:
    """Unified LLM client for llm_analytics."""

    def __init__(
        self,
        provider_key: "LLMProviderKey | None" = None,
        config: "ProviderConfig | None" = None,
        distinct_id: str = "",
        trace_id: str | None = None,
        properties: dict[str, Any] | None = None,
        groups: dict[str, Any] | None = None,
        capture_analytics: bool = True,
    ):
        self.provider_key = provider_key
        self.config = config
        self.analytics = AnalyticsContext(
            distinct_id=distinct_id,
            trace_id=trace_id or str(uuid.uuid4()),
            properties=properties,
            groups=groups,
            capture=capture_analytics,
        )

    def _get_api_key(self) -> str | None:
        """Extract API key from provider key if set."""
        if self.provider_key is None:
            return None
        return self.provider_key.encrypted_config.get("api_key")

    def _validate_provider(self, request_provider: str) -> None:
        """Validate that the request provider is served by the provider key."""
        if self.provider_key is not None and not _providers_compatible(self.provider_key.provider, request_provider):
            raise ProviderMismatchError(self.provider_key.provider, request_provider)

    def _resolve_provider(self, request_provider: str) -> str:
        """Return the provider to route through, treating the key as authoritative.

        An azure_openai key serves the OpenAI model namespace, so an "openai"
        request is routed through Azure rather than the OpenAI adapter.
        """
        if self.provider_key is not None and _providers_compatible(self.provider_key.provider, request_provider):
            return self.provider_key.provider
        return request_provider

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Non-streaming completion."""
        self._validate_provider(request.provider)
        provider = _get_provider(self._resolve_provider(request.provider), self.provider_key)
        api_key, base_url = self._resolve_credentials()
        return provider.complete(request, api_key, self.analytics, base_url)

    def stream(self, request: CompletionRequest) -> Generator[StreamChunk]:
        """Streaming completion."""
        self._validate_provider(request.provider)
        provider = _get_provider(self._resolve_provider(request.provider), self.provider_key)
        api_key, base_url = self._resolve_credentials()
        yield from provider.stream(request, api_key, self.analytics, base_url)

    def _resolve_credentials(self) -> tuple[str | None, str | None]:
        """Get api_key and base_url from config or provider_key."""
        if self.config:
            return self.config.api_key, self.config.base_url
        return self._get_api_key(), None

    @classmethod
    def validate_key(cls, provider: str, api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an API key for a provider. Returns (state, error_message)."""
        return _get_provider(provider).validate_key(api_key, **kwargs)

    @classmethod
    def list_models(cls, provider: str, api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available models for a provider."""
        return _get_provider(provider).list_models(api_key, **kwargs)

    @classmethod
    def recommended_models(cls, provider: str) -> set[str]:
        """Return the set of curated/recommended model IDs for a provider."""
        return _get_provider(provider).recommended_models()


def _get_provider(name: str, provider_key: "LLMProviderKey | None" = None) -> "Provider":
    """Get provider by name. For Azure, reads extra config from provider_key."""
    from typing import cast

    from products.ai_observability.backend.llm.providers.anthropic import AnthropicAdapter
    from products.ai_observability.backend.llm.providers.azure_openai import DEFAULT_API_VERSION, AzureOpenAIAdapter
    from products.ai_observability.backend.llm.providers.fireworks import FireworksAdapter
    from products.ai_observability.backend.llm.providers.gemini import GeminiAdapter
    from products.ai_observability.backend.llm.providers.minimax import MiniMaxAdapter
    from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter
    from products.ai_observability.backend.llm.providers.openrouter import OpenRouterAdapter
    from products.ai_observability.backend.llm.providers.together import TogetherAdapter
    from products.ai_observability.backend.llm.providers.zeabur import ZeaburAdapter

    match name:
        case "openai":
            return cast("Provider", OpenAIAdapter())
        case "anthropic":
            return cast("Provider", AnthropicAdapter())
        case "gemini":
            return cast("Provider", GeminiAdapter())
        case "together_ai":
            return cast("Provider", TogetherAdapter())
        case "openrouter":
            return cast("Provider", OpenRouterAdapter())
        case "fireworks":
            return cast("Provider", FireworksAdapter())
        case "minimax":
            return cast("Provider", MiniMaxAdapter())
        case "zeabur":
            return cast("Provider", ZeaburAdapter())
        case "azure_openai":
            config = provider_key.encrypted_config if provider_key else {}
            return cast(
                "Provider",
                AzureOpenAIAdapter(
                    azure_endpoint=config.get("azure_endpoint", ""),
                    api_version=config.get("api_version", DEFAULT_API_VERSION),
                ),
            )
        case _:
            raise UnsupportedProviderError(name)
