import pytest
from unittest.mock import MagicMock, patch

import openai

from products.ai_observability.backend.llm.providers.minimax import MINIMAX_BASE_URL, MiniMaxAdapter


class TestMiniMaxValidateKey:
    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_validate_key_valid_returns_ok(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("minimax-test-key")

        assert state == "ok"
        assert message is None

    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_validate_key_auth_error_returns_invalid(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.AuthenticationError(
            message="Invalid key",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("minimax-test-key")

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_validate_key_connection_error_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("minimax-test-key")

        assert state == "error"
        assert message == "Could not connect to MiniMax"

    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_validate_key_rate_limit_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("minimax-test-key")

        assert state == "error"
        assert message == "Rate limited, please try again later"


class TestMiniMaxListModels:
    def test_list_models_without_key_returns_empty(self):
        assert MiniMaxAdapter.list_models(None) == []

    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_list_models_with_key_returns_newest_first(self, mock_openai):
        model_older = MagicMock()
        model_older.id = "MiniMax-M2"
        model_older.created = 1700000000

        model_newer = MagicMock()
        model_newer.id = "MiniMax-M2.5"
        model_newer.created = 1710000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model_older, model_newer]
        mock_openai.return_value = mock_client

        models = MiniMaxAdapter.list_models("minimax-test-key")

        assert models == ["MiniMax-M2.5", "MiniMax-M2"]

    @patch(
        "products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI",
        side_effect=Exception("API error"),
    )
    def test_list_models_error_returns_empty(self, _mock_openai):
        assert MiniMaxAdapter.list_models("minimax-test-key") == []

    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_list_models_uses_minimax_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        MiniMaxAdapter.list_models("minimax-test-key")

        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == MINIMAX_BASE_URL


class TestMiniMaxRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert MiniMaxAdapter.recommended_models() == set()


class TestMiniMaxDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            MiniMaxAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = MiniMaxAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()
