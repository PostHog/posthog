import pytest
from unittest.mock import MagicMock, patch

import httpx
import anthropic
from parameterized import parameterized

from products.ai_observability.backend.llm.errors import (
    ContextWindowExceededError,
    ModelNotFoundError,
    ModelPermissionError,
)
from products.ai_observability.backend.llm.providers.anthropic import AnthropicAdapter, AnthropicConfig
from products.ai_observability.backend.llm.types import AnalyticsContext, CompletionRequest


class TestAnthropicListModels:
    def test_list_models_without_key_returns_supported(self):
        assert AnthropicAdapter.list_models(None) == AnthropicConfig.SUPPORTED_MODELS

    @patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_list_models_with_key_returns_supported_plus_api_models_newest_first(self, mock_anthropic):
        api_model_supported = MagicMock()
        api_model_supported.id = "claude-opus-4-5"
        api_model_supported.created_at = "2025-06-01T00:00:00Z"

        api_model_new = MagicMock()
        api_model_new.id = "claude-5-opus"
        api_model_new.created_at = "2026-03-01T00:00:00Z"

        api_model_old = MagicMock()
        api_model_old.id = "claude-3-haiku-20240307"
        api_model_old.created_at = "2024-03-07T00:00:00Z"

        mock_page = MagicMock()
        mock_page.data = [api_model_supported, api_model_new, api_model_old]

        mock_client = MagicMock()
        mock_client.models.list.return_value = mock_page
        mock_anthropic.return_value = mock_client

        models = AnthropicAdapter.list_models("sk-ant-test-key")

        # Supported models first, then API models sorted by created_at newest first
        assert models == [*AnthropicConfig.SUPPORTED_MODELS, "claude-5-opus", "claude-3-haiku-20240307"]

    @patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_list_models_filters_non_claude_models(self, mock_anthropic):
        claude_model = MagicMock()
        claude_model.id = "claude-instant-1.2"

        non_claude_model = MagicMock()
        non_claude_model.id = "some-other-model"

        mock_page = MagicMock()
        mock_page.data = [claude_model, non_claude_model]

        mock_client = MagicMock()
        mock_client.models.list.return_value = mock_page
        mock_anthropic.return_value = mock_client

        models = AnthropicAdapter.list_models("sk-ant-test-key")

        assert "claude-instant-1.2" in models
        assert "some-other-model" not in models

    @patch(
        "products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic",
        side_effect=Exception("API error"),
    )
    def test_list_models_error_returns_supported(self, _mock_anthropic):
        assert AnthropicAdapter.list_models("sk-ant-test-key") == AnthropicConfig.SUPPORTED_MODELS


class TestAnthropicRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert AnthropicAdapter.recommended_models() == set(AnthropicConfig.SUPPORTED_MODELS)


class TestAnthropicTemperature:
    def _make_mock_response(self):
        mock_block = MagicMock()
        mock_block.text = "yes"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        return mock_response

    def _complete_with_model(self, model: str, temperature: float | None = None):
        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = self._make_mock_response()

            AnthropicAdapter().complete(
                CompletionRequest(
                    model=model,
                    messages=[{"role": "user", "content": "hi"}],
                    provider="anthropic",
                    system="s",
                    temperature=temperature,
                ),
                api_key="sk-ant-test",
                analytics=AnalyticsContext(capture=False),
            )
            return mock_client.messages.create.call_args.kwargs

    def _stream_with_model(self, model: str, temperature: float | None = None):
        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = iter([])

            # stream() is a generator; drain it so the request is actually built and sent
            list(
                AnthropicAdapter().stream(
                    CompletionRequest(
                        model=model,
                        messages=[{"role": "user", "content": "hi"}],
                        provider="anthropic",
                        system="s",
                        temperature=temperature,
                    ),
                    api_key="sk-ant-test",
                    analytics=AnalyticsContext(capture=False),
                )
            )
            return mock_client.messages.create.call_args.kwargs

    @parameterized.expand(["claude-haiku-4-5", "claude-opus-4-8", "claude-fable-5"])
    def test_temperature_omitted_when_not_set(self, model: str):
        # Evals never set a temperature; we must not inject one (Anthropic's guidance is to omit,
        # and injecting temperature=0 is what 400'd on models where it's deprecated)
        assert "temperature" not in self._complete_with_model(model, temperature=None)
        assert "temperature" not in self._stream_with_model(model, temperature=None)

    @parameterized.expand(["claude-haiku-4-5", "claude-opus-4-6"])
    def test_explicit_temperature_forwarded(self, model: str):
        assert self._complete_with_model(model, temperature=0.5)["temperature"] == 0.5
        assert self._stream_with_model(model, temperature=0.5)["temperature"] == 0.5


def _make_bad_request_error(message: str) -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=400, request=request, json={"error": {"message": message}})
    return anthropic.BadRequestError(message, response=response, body={"error": {"message": message}})


def _make_not_found_error(model: str) -> anthropic.NotFoundError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    message = f"model: {model}"
    response = httpx.Response(status_code=404, request=request, json={"error": {"message": message}})
    return anthropic.NotFoundError(message, response=response, body={"error": {"message": message}})


def _make_permission_denied_error(model: str) -> anthropic.PermissionDeniedError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    message = f"Your API key does not have access to {model}"
    response = httpx.Response(status_code=403, request=request, json={"error": {"message": message}})
    return anthropic.PermissionDeniedError(message, response=response, body={"error": {"message": message}})


def _raising_stream(error: Exception):
    """A stream that fails partway through iteration, the way an overload does."""
    yield MagicMock(type="message_start", message=MagicMock(usage=MagicMock(input_tokens=1, output_tokens=0)))
    raise error


class TestAnthropicErrorMapping:
    @parameterized.expand(
        [
            ("prompt_too_long", "prompt is too long: 300000 tokens > 200000 maximum"),
            ("input_tokens_exceed", "input tokens exceed the maximum allowed for this model"),
        ]
    )
    def test_context_window_400_maps_to_context_window_exceeded(self, _name: str, message: str):
        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = _make_bad_request_error(message)

            with pytest.raises(ContextWindowExceededError):
                AnthropicAdapter().complete(
                    CompletionRequest(
                        model="claude-haiku-4-5",
                        messages=[{"role": "user", "content": "hi"}],
                        provider="anthropic",
                        system="s",
                    ),
                    api_key="sk-ant-test",
                    analytics=AnalyticsContext(capture=False),
                )

    def test_model_404_maps_to_model_not_found(self):
        # A retired or misspelled model comes back as a 404. Unmapped, an evaluation burned its
        # Temporal retries instead of disabling itself with a reason.
        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = _make_not_found_error("claude-3-sonnet-20240229")

            with pytest.raises(ModelNotFoundError):
                AnthropicAdapter().complete(
                    CompletionRequest(
                        model="claude-3-sonnet-20240229",
                        messages=[{"role": "user", "content": "hi"}],
                        provider="anthropic",
                        system="s",
                    ),
                    api_key="sk-ant-test",
                    analytics=AnalyticsContext(capture=False),
                )

    def test_model_403_maps_to_model_permission_error(self):
        # A 403 resolves to the `permission_error` spec, which disables the evaluation and marks
        # the key errored — so this mapping decides more than the wording of a message.
        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = _make_permission_denied_error("claude-opus-4-5")

            with pytest.raises(ModelPermissionError):
                AnthropicAdapter().complete(
                    CompletionRequest(
                        model="claude-opus-4-5",
                        messages=[{"role": "user", "content": "hi"}],
                        provider="anthropic",
                        system="s",
                    ),
                    api_key="sk-ant-test",
                    analytics=AnalyticsContext(capture=False),
                )


class TestAnthropicStreamErrorSurfacing:
    def test_model_404_yields_actionable_message_instead_of_discarding_the_reason(self):
        # Streaming has no exception channel, so this chunk is the entire explanation the user
        # gets in the playground.
        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = _make_not_found_error("claude-3-sonnet-20240229")

            chunks = list(
                AnthropicAdapter().stream(
                    CompletionRequest(
                        model="claude-3-sonnet-20240229",
                        messages=[{"role": "user", "content": "hi"}],
                        provider="anthropic",
                        system="s",
                    ),
                    api_key="sk-ant-test",
                    analytics=AnalyticsContext(capture=False),
                )
            )

        errors = [chunk.data["error"] for chunk in chunks if chunk.type == "error"]
        assert errors == ["Model 'claude-3-sonnet-20240229' is not available. Pick a different model and try again."]

    def test_error_raised_partway_through_the_stream_still_reaches_the_user(self):
        # An overload arrives during iteration, not when the request is made. That path used to
        # sit outside the try, so the generator raised and the playground showed nothing at all.
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        overloaded = anthropic.RateLimitError(
            "Overloaded",
            response=httpx.Response(status_code=429, request=request, json={"error": {"message": "Overloaded"}}),
            body={"error": {"message": "Overloaded"}},
        )

        with patch("products.ai_observability.backend.llm.providers.anthropic.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _raising_stream(overloaded)

            chunks = list(
                AnthropicAdapter().stream(
                    CompletionRequest(
                        model="claude-haiku-4-5",
                        messages=[{"role": "user", "content": "hi"}],
                        provider="anthropic",
                        system="s",
                    ),
                    api_key="sk-ant-test",
                    analytics=AnalyticsContext(capture=False),
                )
            )

        errors = [chunk.data["error"] for chunk in chunks if chunk.type == "error"]
        assert errors == ["The provider is rate limiting this key. Wait a moment, then try again."]
