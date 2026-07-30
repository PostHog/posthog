from unittest.mock import MagicMock, patch

from products.ai_observability.backend.llm.providers.zeabur import ZEABUR_BASE_URL, ZeaburAdapter

# Error mapping and BYOK-only behavior of the shared adapter are covered in
# test_fireworks.py / test_minimax.py; these tests only cover the Zeabur wiring.


class TestZeaburAdapter:
    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_validate_key_uses_zeabur_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = ZeaburAdapter.validate_key("sk-zeabur-test-key")

        assert state == "ok"
        assert message is None
        assert mock_openai.call_args.kwargs["base_url"] == ZEABUR_BASE_URL

    @patch("products.ai_observability.backend.llm.providers.openai_compatible_byok.openai.OpenAI")
    def test_list_models_uses_zeabur_base_url(self, mock_openai):
        model = MagicMock()
        model.id = "claude-sonnet-4-5"
        model.created = 1700000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model]
        mock_openai.return_value = mock_client

        models = ZeaburAdapter.list_models("sk-zeabur-test-key")

        assert models == ["claude-sonnet-4-5"]
        assert mock_openai.call_args.kwargs["base_url"] == ZEABUR_BASE_URL
