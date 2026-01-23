import pytest
from unittest.mock import MagicMock, patch

from posthog.llm.gateway_client import ANTHROPIC_TO_OPENAI_FALLBACK, VALID_PRODUCTS, LLMClient, get_llm_client


class TestGetLlmClient:
    @pytest.mark.parametrize("product", ["llm_gateway", "array", "wizard", "django"])
    def test_valid_products(self, product: str):
        assert product in VALID_PRODUCTS

    def test_invalid_product_raises_error(self):
        with pytest.raises(ValueError, match="Invalid product 'invalid'"):
            get_llm_client(product="invalid")

    @patch("posthog.llm.gateway_client.posthoganalytics")
    @patch("posthog.llm.gateway_client.settings")
    def test_returns_gateway_client_when_feature_enabled(self, mock_settings, mock_posthog):
        mock_posthog.feature_enabled.return_value = True
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"
        mock_settings.OPENAI_API_KEY = "openai-key"

        client = get_llm_client(team_id=123)

        assert isinstance(client, LLMClient)
        assert client._client.base_url == "http://gateway:8080/django/v1/"
        assert client._client.api_key == "test-key"
        assert client._model_mapping == {}

    @patch("posthog.llm.gateway_client.posthoganalytics")
    @patch("posthog.llm.gateway_client.settings")
    def test_returns_openai_client_when_feature_disabled(self, mock_settings, mock_posthog):
        mock_posthog.feature_enabled.return_value = False
        mock_settings.OPENAI_API_KEY = "openai-key"

        client = get_llm_client(team_id=123)

        assert isinstance(client, LLMClient)
        assert "api.openai.com" in str(client._client.base_url)
        assert client._client.api_key == "openai-key"
        assert client._model_mapping == ANTHROPIC_TO_OPENAI_FALLBACK

    @patch("posthog.llm.gateway_client.posthoganalytics")
    @patch("posthog.llm.gateway_client.settings")
    def test_returns_openai_client_when_gateway_url_missing(self, mock_settings, mock_posthog):
        mock_posthog.feature_enabled.return_value = True
        mock_settings.LLM_GATEWAY_URL = ""
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"
        mock_settings.OPENAI_API_KEY = "openai-key"

        client = get_llm_client(team_id=123)

        assert "api.openai.com" in str(client._client.base_url)

    @patch("posthog.llm.gateway_client.posthoganalytics")
    @patch("posthog.llm.gateway_client.settings")
    def test_feature_flag_called_with_team_id(self, mock_settings, mock_posthog):
        mock_posthog.feature_enabled.return_value = False
        mock_settings.OPENAI_API_KEY = "openai-key"

        get_llm_client(product="wizard", team_id=456)

        mock_posthog.feature_enabled.assert_called_once_with(
            "use-llm-gateway",
            "456",
            groups={"project": "456"},
            send_feature_flag_events=False,
        )

    @patch("posthog.llm.gateway_client.posthoganalytics")
    @patch("posthog.llm.gateway_client.settings")
    def test_feature_flag_called_with_default_when_no_team_id(self, mock_settings, mock_posthog):
        mock_posthog.feature_enabled.return_value = False
        mock_settings.OPENAI_API_KEY = "openai-key"

        get_llm_client(product="wizard")

        mock_posthog.feature_enabled.assert_called_once_with(
            "use-llm-gateway",
            "default",
            groups=None,
            send_feature_flag_events=False,
        )


class TestLLMClientModelMapping:
    @pytest.mark.parametrize(
        "anthropic_model,expected_openai",
        [
            ("claude-opus-4-5", "gpt-5.2"),
            ("claude-sonnet-4-5", "gpt-5-mini"),
            ("claude-haiku-4-5", "gpt-5-nano"),
        ],
    )
    def test_fallback_mapping_values(self, anthropic_model: str, expected_openai: str):
        assert ANTHROPIC_TO_OPENAI_FALLBACK[anthropic_model] == expected_openai

    def test_model_mapping_applied_via_chat_completions(self):
        mock_openai = MagicMock()
        client = LLMClient(mock_openai, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)

        client.chat.completions.create(model="claude-opus-4-5", messages=[])

        mock_openai.chat.completions.create.assert_called_once_with(model="gpt-5.2", messages=[])

    def test_model_mapping_applied_via_beta_chat_completions(self):
        mock_openai = MagicMock()
        client = LLMClient(mock_openai, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)

        client.beta.chat.completions.parse(model="claude-sonnet-4-5", messages=[])

        mock_openai.beta.chat.completions.parse.assert_called_once_with(model="gpt-5-mini", messages=[])

    def test_openai_model_unchanged(self):
        mock_openai = MagicMock()
        client = LLMClient(mock_openai, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)

        client.chat.completions.create(model="gpt-5.2", messages=[])

        mock_openai.chat.completions.create.assert_called_once_with(model="gpt-5.2", messages=[])

    def test_no_mapping_when_empty(self):
        mock_openai = MagicMock()
        client = LLMClient(mock_openai, model_mapping={})

        client.chat.completions.create(model="claude-opus-4-5", messages=[])

        mock_openai.chat.completions.create.assert_called_once_with(model="claude-opus-4-5", messages=[])

    def test_other_kwargs_preserved(self):
        mock_openai = MagicMock()
        client = LLMClient(mock_openai, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)

        client.chat.completions.create(
            model="claude-haiku-4-5",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.5,
            user="test-user",
        )

        mock_openai.chat.completions.create.assert_called_once_with(
            model="gpt-5-nano",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.5,
            user="test-user",
        )

    def test_embeddings_model_mapping(self):
        mock_openai = MagicMock()
        client = LLMClient(mock_openai, model_mapping={"text-embedding-anthropic": "text-embedding-3-small"})

        client.embeddings.create(model="text-embedding-anthropic", input="hello")

        mock_openai.embeddings.create.assert_called_once_with(model="text-embedding-3-small", input="hello")

    def test_return_value_passed_through(self):
        mock_openai = MagicMock()
        expected_response = {"id": "chatcmpl-123", "choices": []}
        mock_openai.chat.completions.create.return_value = expected_response
        client = LLMClient(mock_openai, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)

        result = client.chat.completions.create(model="claude-opus-4-5", messages=[])

        assert result == expected_response

    def test_method_without_model_param(self):
        mock_openai = MagicMock()
        mock_openai.models.list.return_value = ["gpt-4", "gpt-5"]
        client = LLMClient(mock_openai, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)

        result = client.models.list()

        mock_openai.models.list.assert_called_once_with()
        assert result == ["gpt-4", "gpt-5"]
