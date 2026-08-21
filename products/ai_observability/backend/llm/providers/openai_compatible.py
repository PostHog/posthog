"""Custom OpenAI-compatible provider for the unified LLM client.

Unlike the fixed-URL adapters built on ``OpenAICompatibleByokAdapter`` (MiniMax,
Zeabur), this provider talks to a user-configured endpoint: the base URL lives in
the provider key's ``encrypted_config`` next to the API key. It is BYOK-only.

The base URL is user-controlled input that our servers send an Authorization
header to, so it is guarded in two layers. ``is_allowed_custom_base_url`` runs the
shared SSRF validator (https only, no internal hosts, no private addresses) at
every entry point, and the connection itself is pinned: ``_pinned_http_client``
resolves the host once and dials that exact address, so a record that rebinds to a
private address after validation has nothing left to redirect. Redirects are not
followed for the same reason, since their targets are never validated.
"""

import logging
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

import httpx
import openai

from posthog.security.pinned_httpx import pinned_transport
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import is_url_allowed

from products.ai_observability.backend.llm.providers._diagnostics import PROVIDER_DEFAULT_LIMITS, tagged_http_client
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

REDIRECT_MESSAGE = "The endpoint redirected to a different address, use that address as the base URL"

# Maps adapter error-message prefixes to the form field they should highlight in the UI.
# Keep aligned with the `return` statements in `OpenAICompatibleAdapter.validate_key` below,
# because editing a message string there without updating this table silently breaks field routing.
# Messages not listed (rate limits, generic failures) have no field attribution and are
# surfaced as toast/banner by the frontend.
_ERROR_FIELD_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("Base URL is required", "base_url"),
    ("Base URL must be", "base_url"),
    ("The endpoint did not return a model list", "base_url"),
    ("The endpoint redirected", "base_url"),
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
    """Return True if the base URL is https:// and passes the shared SSRF validator."""
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    allowed, _reason = is_url_allowed(base_url)
    return allowed


def _pinned_http_client(base_url: str) -> httpx.Client:
    """Build a client that can only reach the address ``base_url`` was validated against.

    Raises ``SSRFBlockedError`` before any connection is opened when validation fails.
    """
    return tagged_http_client(
        timeout=OpenAIConfig.TIMEOUT,
        transport=pinned_transport(base_url, limits=PROVIDER_DEFAULT_LIMITS),
        follow_redirects=False,
    )


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

    def _build_http_client(self, base_url: str | None) -> httpx.Client:
        """Pin the connection to the configured endpoint's validated address.

        Ignores the argument in favor of ``self.base_url``: that is the value
        ``complete`` / ``stream`` checked, so pinning anything else would dial an
        address that passed no validation.
        """
        return _pinned_http_client(self._require_allowed_base_url())

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
            with _pinned_http_client(base_url) as http_client:
                client = openai.OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=OpenAIConfig.TIMEOUT,
                    http_client=http_client,
                )
                client.models.list()
            return (LLMProviderKey.State.OK, None)
        except SSRFBlockedError:
            return (LLMProviderKey.State.INVALID, DISALLOWED_BASE_URL_MESSAGE)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.NotFoundError:
            return (LLMProviderKey.State.INVALID, "The endpoint did not return a model list, check the base URL")
        except openai.APIStatusError as e:
            # Redirects reach the caller as a status error because the client never follows
            # them, so name the case instead of leaving the generic failure message.
            if 300 <= e.status_code < 400:
                return (LLMProviderKey.State.INVALID, REDIRECT_MESSAGE)
            logger.exception("%s key validation error", PROVIDER_DISPLAY_NAME)
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")
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
            with _pinned_http_client(base_url) as http_client:
                client = openai.OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=OpenAIConfig.TIMEOUT,
                    http_client=http_client,
                )
                # `created` is required by the OpenAI schema but arbitrary endpoints omit it, and
                # the SDK then hands back None. Sorting two of those raises, and the except below
                # would turn that into an empty picker with nothing explaining why.
                return [m.id for m in sorted(client.models.list(), key=lambda m: m.created or 0, reverse=True)]
        except SSRFBlockedError:
            return []
        except Exception:
            logger.exception("Error listing %s models", PROVIDER_DISPLAY_NAME)
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError(f"{PROVIDER_DISPLAY_NAME} is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError(f"{PROVIDER_DISPLAY_NAME} is BYOKEY-only. No default API key is available.")
