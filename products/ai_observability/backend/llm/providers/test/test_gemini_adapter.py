import pytest
from unittest.mock import MagicMock, patch

import httpx
from google.genai.errors import ClientError
from parameterized import parameterized

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    RateLimitError,
)
from products.ai_observability.backend.llm.providers.gemini import GeminiAdapter, GeminiConfig
from products.ai_observability.backend.llm.types import AnalyticsContext, CompletionRequest


class TestGeminiRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert GeminiAdapter.recommended_models() == set(GeminiConfig.SUPPORTED_MODELS)


def _make_client_error(code: int, status: str, message: str) -> ClientError:
    return ClientError(code, {"error": {"code": code, "status": status, "message": message}})


class TestGeminiAdapterErrorMapping:
    @parameterized.expand(
        [
            # Retired/deprecated model: Google returns a 404 or a message saying it's gone.
            ("404_not_found", 404, "NOT_FOUND", "model not found", ModelNotFoundError),
            (
                "deprecated_message",
                400,
                "INVALID_ARGUMENT",
                "This model is no longer available",
                ModelNotFoundError,
            ),
            ("403_permission", 403, "PERMISSION_DENIED", "permission denied", ModelPermissionError),
            ("401_auth", 401, "UNAUTHENTICATED", "invalid api key", AuthenticationError),
            ("429_rate_limit", 429, "RESOURCE_EXHAUSTED", "rate limit exceeded", RateLimitError),
        ]
    )
    def test_api_error_is_mapped_to_llm_error(
        self,
        _name: str,
        code: int,
        status: str,
        message: str,
        expected: type[Exception],
    ):
        request = CompletionRequest(
            model="gemini-2.0-flash-lite",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="gemini",
        )
        adapter = GeminiAdapter()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _make_client_error(code, status, message)

        with patch("products.ai_observability.backend.llm.providers.gemini.genai.Client", return_value=mock_client):
            with pytest.raises(expected):
                adapter.complete(request, api_key="test-key", analytics=AnalyticsContext(capture=False))

    def test_transport_error_is_mapped_to_provider_connection_error(self):
        # google-genai leaks raw httpx transport errors (connection reset) rather than wrapping
        # them in APIError, so they'd escape the mapping above without a dedicated branch.
        request = CompletionRequest(
            model="gemini-2.0-flash-lite",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="gemini",
        )
        adapter = GeminiAdapter()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = httpx.ReadError("[Errno 104] Connection reset by peer")

        with patch("products.ai_observability.backend.llm.providers.gemini.genai.Client", return_value=mock_client):
            with pytest.raises(ProviderConnectionError):
                adapter.complete(request, api_key="test-key", analytics=AnalyticsContext(capture=False))


class TestGeminiStreamErrorSurfacing:
    def test_retired_model_yields_actionable_message_instead_of_discarding_the_reason(self):
        # Streaming has no exception channel, so this chunk is the entire explanation the user
        # gets in the playground.
        request = CompletionRequest(
            model="gemini-1.0-pro",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="gemini",
        )
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.side_effect = _make_client_error(
            404, "NOT_FOUND", "models/gemini-1.0-pro is not found"
        )

        with patch("products.ai_observability.backend.llm.providers.gemini.genai.Client", return_value=mock_client):
            chunks = list(
                GeminiAdapter().stream(request, api_key="test-key", analytics=AnalyticsContext(capture=False))
            )

        errors = [chunk.data["error"] for chunk in chunks if chunk.type == "error"]
        assert errors == ["Model 'gemini-1.0-pro' is not available. Pick a different model and try again."]
