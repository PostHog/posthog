"""Custom OpenAI-compatible provider for the unified LLM client.

Unlike the fixed-URL adapters built on ``OpenAICompatibleByokAdapter`` (MiniMax,
Zeabur), this provider talks to a user-configured endpoint: the base URL lives in
the provider key's ``encrypted_config`` next to the API key. It is BYOK-only.

The base URL is user-controlled input that our servers send an Authorization
header to, so every entry point re-checks it against ``is_allowed_custom_base_url``
before a client is constructed. The check requires https and a hostname that
resolves to a public IP, which keeps the user's key off plaintext transports and
blocks requests to internal services (cloud metadata, cluster-local hosts).
"""

import logging
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

import openai

from posthog.api.utils import raise_if_user_provided_url_unsafe

from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

PROVIDER_DISPLAY_NAME = "OpenAI-compatible"

# Shared error message used by both the adapter (for `Client.validate_key` callers) and the
# serializer layer (so the error attributes to the base_url field in the UI). Keep as a
# single source of truth because the two layers must agree.
DISALLOWED_BASE_URL_MESSAGE = "Base URL must be a public https:// URL (e.g. https://api.example.com/v1)"

# Maps adapter error-message prefixes to the form field they should highlight in the UI.
# Keep aligned with the `return` statements in `OpenAICompatibleAdapter.validate_key` below,
# because editing a message string there without updating this table silently breaks field routing.
# Messages not listed (rate limits, generic failures) have no field attribution and are
# surfaced as toast/banner by the frontend.
_ERROR_FIELD_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("Base URL is required", "base_url"),
    ("Base URL must be", "base_url"),
    ("The endpoint did not return a model list", "base_url"),
    ("Could not connect to the endpoint", "base_url"),
    ("Invalid API key", "api_key"),
)


def error_field_for_validation_message(error_message: str | None) -> str | None:
    """Map a `validate_key` error message to the UI form field that should be highlighted."""
    if not error_message:
        return None
    return next(
        (field for prefix, field in _ERROR_FIELD_BY_PREFIX if error_message.startswith(prefix)),
        None,
    )


def is_allowed_custom_base_url(base_url: str) -> bool:
    """Return True if the base URL is https:// and its hostname resolves to a public IP."""
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    try:
        raise_if_user_provided_url_unsafe(base_url)
    except ValueError:
        return False
    return True


class OpenAICompatibleAdapter(OpenAIAdapter):
    """Provider for user-configured OpenAI-compatible endpoints.

    Note on the kwargs / instance-attr split: static methods (`validate_key`,
    `list_models`) take ``base_url`` via ``**kwargs`` because they run *before* an
    ``LLMProviderKey`` exists on disk (pre-save validation, pre-validation viewset).
    The instance method path (`complete` / `stream`) reads from ``self`` because by
    the time it runs the adapter has been built from a persisted
    ``LLMProviderKey.encrypted_config``.
    """

    name = "openai_compatible"

    def __init__(self, base_url: str = ""):
        self.base_url = base_url

    def _require_allowed_base_url(self) -> str:
        """Return the configured base URL, or raise before any client is built.

        Without this guard an empty base URL would fall through to
        ``settings.OPENAI_BASE_URL`` in ``OpenAIAdapter.complete`` and send the
        user's key to the wrong host.
        """
        if not is_allowed_custom_base_url(self.base_url):
            raise ValueError(DISALLOWED_BASE_URL_MESSAGE)
        return self.base_url

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=self._require_allowed_base_url())

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk]:
        yield from super().stream(request, api_key, analytics, base_url=self._require_allowed_base_url())

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an API key by listing models on the configured endpoint."""
        from products.ai_observability.backend.models.provider_keys import LLMProviderKey

        base_url = kwargs.get("base_url", "")

        if not base_url:
            return (LLMProviderKey.State.INVALID, "Base URL is required")

        if not is_allowed_custom_base_url(base_url):
            return (LLMProviderKey.State.INVALID, DISALLOWED_BASE_URL_MESSAGE)

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.NotFoundError:
            return (LLMProviderKey.State.INVALID, "The endpoint did not return a model list, check the base URL")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to the endpoint")
        except Exception:
            logger.exception("%s key validation error", PROVIDER_DISPLAY_NAME)
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List models on the configured endpoint. Returns empty list without a key (BYOK-only)."""
        if not api_key:
            return []

        base_url = kwargs.get("base_url", "")
        if not is_allowed_custom_base_url(base_url):
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=OpenAIConfig.TIMEOUT,
            )
            return [m.id for m in sorted(client.models.list(), key=lambda m: m.created, reverse=True)]
        except Exception:
            logger.exception("Error listing %s models", PROVIDER_DISPLAY_NAME)
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError(f"{PROVIDER_DISPLAY_NAME} is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError(f"{PROVIDER_DISPLAY_NAME} is BYOKEY-only. No default API key is available.")
