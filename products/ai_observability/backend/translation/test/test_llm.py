"""Tests for translation LLM module."""

import pytest
from unittest.mock import MagicMock, patch

import httpx
from openai import APITimeoutError
from parameterized import parameterized

from products.ai_observability.backend.translation.constants import SUPPORTED_LANGUAGES, TRANSLATION_MODEL
from products.ai_observability.backend.translation.llm import TranslationTimeoutError, translate_text

MOCK_PATH = "products.ai_observability.backend.translation.llm.get_llm_client"


def mock_llm_client(mock_get_client: MagicMock) -> MagicMock:
    # Self-referential so `with_options(...)` returns the same client the assertions inspect.
    client = MagicMock()
    client.with_options.return_value = client
    mock_get_client.return_value = client
    return client


def mock_completion(client: MagicMock, content: str | None) -> None:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = response


class TestTranslateText:
    @patch(MOCK_PATH)
    def test_returns_translated_text(self, mock_get_client):
        mock_completion(mock_llm_client(mock_get_client), "  Hola mundo  ")

        result = translate_text("Hello world", "es")

        assert result == "Hola mundo"

    @patch(MOCK_PATH)
    def test_uses_correct_model(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", "es")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == TRANSLATION_MODEL

    @patch(MOCK_PATH)
    def test_uses_fallback_user_when_no_distinct_id(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", "es")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["user"] == "llma-translation"

    @patch(MOCK_PATH)
    def test_passes_distinct_id_as_user(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", "es", user_distinct_id="user-123")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["user"] == "user-123"

    @patch(MOCK_PATH)
    def test_creates_client_with_correct_product(self, mock_get_client):
        mock_completion(mock_llm_client(mock_get_client), "Translated")

        translate_text("Test", "es")

        mock_get_client.assert_called_once_with("llma_translation")

    @patch(MOCK_PATH)
    def test_disables_client_retries(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", "es")

        # Restoring the SDK's default two retries makes a caller wait three timeouts for an error.
        mock_client.with_options.assert_called_once_with(max_retries=0)

    @parameterized.expand(list(SUPPORTED_LANGUAGES.items()))
    @patch(MOCK_PATH)
    def test_includes_language_name_in_prompt(self, lang_code, lang_name, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", lang_code)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_message = call_kwargs["messages"][0]["content"]
        assert lang_name in system_message

    @patch(MOCK_PATH)
    def test_falls_back_to_language_code_for_unknown_language(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", "unknown_lang")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_message = call_kwargs["messages"][0]["content"]
        assert "unknown_lang" in system_message

    @patch(MOCK_PATH)
    def test_passes_text_as_user_message(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Hello world", "es")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_message = call_kwargs["messages"][1]
        assert user_message["role"] == "user"
        assert user_message["content"] == "Hello world"

    @patch(MOCK_PATH)
    def test_returns_empty_string_for_none_content(self, mock_get_client):
        mock_completion(mock_llm_client(mock_get_client), None)

        result = translate_text("Test", "es")

        assert result == ""

    @patch(MOCK_PATH)
    def test_strips_whitespace_from_response(self, mock_get_client):
        mock_completion(mock_llm_client(mock_get_client), "\n\n  Translated text  \n\n")

        result = translate_text("Test", "es")

        assert result == "Translated text"

    @patch(MOCK_PATH)
    def test_propagates_exceptions(self, mock_get_client):
        mock_llm_client(mock_get_client).chat.completions.create.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            translate_text("Test", "es")

    @patch(MOCK_PATH)
    def test_raises_translation_timeout_error_on_api_timeout(self, mock_get_client):
        mock_llm_client(mock_get_client).chat.completions.create.side_effect = APITimeoutError(
            request=httpx.Request("POST", "http://gateway.invalid/chat/completions")
        )

        # The API layer maps only this type to a 504, so a raw APITimeoutError would surface as a 500.
        with pytest.raises(TranslationTimeoutError):
            translate_text("Test", "es")

    @patch(MOCK_PATH)
    def test_sets_timeout(self, mock_get_client):
        mock_client = mock_llm_client(mock_get_client)
        mock_completion(mock_client, "Translated")

        translate_text("Test", "es")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["timeout"] == 45.0
