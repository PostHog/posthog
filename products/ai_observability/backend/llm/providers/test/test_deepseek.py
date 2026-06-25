import pytest
from unittest.mock import MagicMock, patch

import openai

from products.ai_observability.backend.llm.providers.deepseek import DEEPSEEK_BASE_URL, DeepSeekAdapter


class TestDeepSeekValidateKey:
    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_validate_key_valid_returns_ok(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = DeepSeekAdapter.validate_key("sk-test-key")

        assert state == "ok"
        assert message is None

    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_validate_key_auth_error_returns_invalid(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.AuthenticationError(
            message="Invalid key",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = DeepSeekAdapter.validate_key("sk-test-key")

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_validate_key_connection_error_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_openai.return_value = mock_client

        state, message = DeepSeekAdapter.validate_key("sk-test-key")

        assert state == "error"
        assert message == "Could not connect to DeepSeek"

    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_validate_key_rate_limit_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = DeepSeekAdapter.validate_key("sk-test-key")

        assert state == "error"
        assert message == "Rate limited, please try again later"

    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_validate_key_uses_deepseek_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        DeepSeekAdapter.validate_key("sk-test-key")

        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == DEEPSEEK_BASE_URL


class TestDeepSeekListModels:
    def test_list_models_without_key_returns_empty(self):
        assert DeepSeekAdapter.list_models(None) == []

    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_list_models_with_key_returns_sorted_by_id(self, mock_openai):
        model_reasoner = MagicMock()
        model_reasoner.id = "deepseek-reasoner"

        model_chat = MagicMock()
        model_chat.id = "deepseek-chat"

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model_reasoner, model_chat]
        mock_openai.return_value = mock_client

        models = DeepSeekAdapter.list_models("sk-test-key")

        assert models == ["deepseek-chat", "deepseek-reasoner"]

    @patch(
        "products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI", side_effect=Exception("API error")
    )
    def test_list_models_error_returns_empty(self, _mock_openai):
        assert DeepSeekAdapter.list_models("sk-test-key") == []

    @patch("products.ai_observability.backend.llm.providers.deepseek.openai.OpenAI")
    def test_list_models_uses_deepseek_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        DeepSeekAdapter.list_models("sk-test-key")

        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == DEEPSEEK_BASE_URL


class TestDeepSeekRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert DeepSeekAdapter.recommended_models() == set()


class TestDeepSeekDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            DeepSeekAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = DeepSeekAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()
