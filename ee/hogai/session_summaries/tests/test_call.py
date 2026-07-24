import pytest
from unittest.mock import patch

from parameterized import parameterized

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL, SESSION_SUMMARIES_MODEL
from ee.hogai.session_summaries.llm.call import _assert_openai_servable_model, call_llm


class TestAssertOpenAIServableModel:
    @parameterized.expand(
        [
            ("gemini_video_model", DEFAULT_VIDEO_UNDERSTANDING_MODEL),
            ("gemini_prefixed", "models/gemini-3-flash-preview"),
            ("gemini_other", "gemini-2.5-flash"),
            ("anthropic", "claude-sonnet-4-6"),
            ("uppercase", "GEMINI-3-FLASH-PREVIEW"),
        ]
    )
    def test_rejects_non_openai_models(self, _name: str, model: str) -> None:
        with pytest.raises(ValueError, match="Non-OpenAI model"):
            _assert_openai_servable_model(model, "session-id")

    @parameterized.expand(
        [
            ("o3", SESSION_SUMMARIES_MODEL),
            ("gpt", "gpt-4o"),
            ("o4_mini", "o4-mini"),
        ]
    )
    def test_allows_openai_models(self, _name: str, model: str) -> None:
        # Should not raise
        _assert_openai_servable_model(model, "session-id")


class TestCallLLMModelGuard:
    async def test_call_llm_rejects_gemini_before_client_setup(self) -> None:
        # The guard must run before the OpenAI client is ever constructed or called,
        # so a misrouted Gemini model never reaches OpenAI for a silent 400.
        with patch("ee.hogai.session_summaries.llm.call.get_async_openai_client") as mock_client:
            with pytest.raises(ValueError, match="Non-OpenAI model"):
                await call_llm(
                    input_prompt="prompt",
                    session_id="session-id",
                    model=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                    user_id=1,
                )
        mock_client.assert_not_called()
