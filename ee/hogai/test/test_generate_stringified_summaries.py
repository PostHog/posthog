from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai.types import GenerateContentConfig
from parameterized import parameterized

from ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries import LLMTraceSummarizerGenerator


def _make_response(text: str | None) -> MagicMock:
    response = MagicMock()
    response.text = text
    return response


class TestLLMTraceSummarizerGeneratorInit(BaseTest):
    @patch("ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries.genai.Client")
    @patch("ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries.settings")
    def test_init_raises_when_api_key_missing(self, mock_settings, mock_client_cls):
        mock_settings.GEMINI_API_KEY = ""

        with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
            LLMTraceSummarizerGenerator(team=self.team)

        mock_client_cls.assert_not_called()

    @patch("ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries.genai.Client")
    @patch("ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries.settings")
    def test_init_constructs_client_with_api_key(self, mock_settings, mock_client_cls):
        mock_settings.GEMINI_API_KEY = "test-key"

        generator = LLMTraceSummarizerGenerator(team=self.team)

        mock_client_cls.assert_called_once_with(api_key="test-key")
        assert generator._client is mock_client_cls.return_value


class TestGenerateTraceSummary(BaseTest):
    def _build_generator(self, response_text: str | None | Exception) -> LLMTraceSummarizerGenerator:
        with (
            patch("ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries.settings") as mock_settings,
            patch("ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries.genai.Client") as mock_client_cls,
        ):
            mock_settings.GEMINI_API_KEY = "test-key"
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            if isinstance(response_text, Exception):
                mock_client.aio.models.generate_content = AsyncMock(side_effect=response_text)
            else:
                mock_client.aio.models.generate_content = AsyncMock(return_value=_make_response(response_text))
            generator = LLMTraceSummarizerGenerator(team=self.team)
        return generator

    @pytest.mark.asyncio
    async def test_passes_temperature_zero_config(self):
        generator = self._build_generator("The user experienced a login issue.")

        await generator._generate_trace_summary(trace_id="t1", stringified_trace="user: hi")

        await_args = cast(AsyncMock, generator._client.aio.models.generate_content).await_args
        assert await_args is not None
        call_kwargs = await_args.kwargs
        assert call_kwargs["model"] == generator._model_id
        assert "user: hi" in call_kwargs["contents"]
        config = call_kwargs["config"]
        assert isinstance(config, GenerateContentConfig)
        assert config.temperature == 0

    @pytest.mark.asyncio
    async def test_returns_cleaned_summary_on_happy_path(self):
        # "The user experienced " prefix gets stripped, then leading "a" is recapitalized
        generator = self._build_generator("The user experienced a login issue.")

        result = await generator._generate_trace_summary(trace_id="t1", stringified_trace="...")

        assert result == "A login issue."

    @parameterized.expand(
        [
            ("title_case", "No issues found"),
            ("lower_case", "no issues found"),
            ("upper_case", "NO ISSUES FOUND"),
        ]
    )
    @pytest.mark.asyncio
    async def test_returns_canonical_no_issues_for_exact_match(self, _name, response_text):
        generator = self._build_generator(response_text)

        result = await generator._generate_trace_summary(trace_id="t1", stringified_trace="...")

        assert result == "No issues found"

    @pytest.mark.asyncio
    async def test_normalizes_no_issues_when_embedded_in_longer_text(self):
        generator = self._build_generator("Based on the conversation, no issues found in the user's interaction.")

        result = await generator._generate_trace_summary(trace_id="t1", stringified_trace="...")

        assert result == "No issues found"

    @pytest.mark.asyncio
    async def test_returns_exception_when_response_text_empty(self):
        generator = self._build_generator("")

        result = await generator._generate_trace_summary(trace_id="t1", stringified_trace="...")

        assert isinstance(result, ValueError)
        assert "No trace summary was generated" in str(result)

    @pytest.mark.asyncio
    async def test_returns_exception_when_api_call_raises(self):
        generator = self._build_generator(RuntimeError("gemini exploded"))

        result = await generator._generate_trace_summary(trace_id="t1", stringified_trace="...")

        assert isinstance(result, RuntimeError)
        assert str(result) == "gemini exploded"
