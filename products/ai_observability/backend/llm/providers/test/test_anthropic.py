from unittest.mock import MagicMock, patch

from parameterized import parameterized

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

    @parameterized.expand(["claude-haiku-4-5", "claude-opus-4-8", "claude-fable-5"])
    def test_temperature_omitted_when_not_set(self, model: str):
        # Evals never set a temperature; we must not inject one (Anthropic's guidance is to omit)
        assert "temperature" not in self._complete_with_model(model, temperature=None)

    @parameterized.expand(["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"])
    def test_explicit_temperature_sent_for_models_that_accept_it(self, model: str):
        assert self._complete_with_model(model, temperature=0.5)["temperature"] == 0.5

    @parameterized.expand(["claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5", "claude-fable-5"])
    def test_explicit_temperature_dropped_for_models_that_reject_it(self, model: str):
        # These 400 with "temperature is deprecated for this model" if we send it
        assert "temperature" not in self._complete_with_model(model, temperature=0.5)
