import json

import pytest
from unittest.mock import MagicMock, patch

import httpx
from openai import RateLimitError
from rest_framework import exceptions

from products.ai_observability.backend.summarization.constants import SUMMARIZATION_FLEX_TIMEOUT, SUMMARIZATION_TIMEOUT
from products.ai_observability.backend.summarization.llm.openai import summarize_with_openai
from products.ai_observability.backend.summarization.llm.schema import SummarizationResponse
from products.ai_observability.backend.summarization.models import OpenAIModel, SummarizationMode


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return RateLimitError("rate limited", response=httpx.Response(429, request=request), body=None)


@pytest.fixture
def valid_response_json():
    return json.dumps(
        {
            "title": "Test Summary",
            "flow_diagram": "User -> Assistant",
            "summary_bullets": [{"text": "Test bullet", "line_refs": "L1"}],
            "interesting_notes": [],
        }
    )


class TestSummarizeWithOpenAI:
    def test_successful_summarization(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            result = summarize_with_openai(
                text_repr="L1: Test content",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            assert isinstance(result, SummarizationResponse)
            assert result.title == "Test Summary"
            mock_get_client.assert_called_once_with(
                "llma_summarization",
                ai_product="aio_summarization",
                properties={"team_id": "1"},
                distinct_id="team-1",
            )

    def test_empty_response_raises_validation_error(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    def test_api_error_raises_api_exception(self):
        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("API Error")

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    def test_uses_correct_model(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == OpenAIModel.GPT_4_1_MINI

    def test_uses_user_id_when_provided(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
                user_id="user-distinct-123",
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["user"] == "user-distinct-123"

    def test_uses_team_fallback_when_no_user_id(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=42,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["user"] == "team-42"

    def test_uses_json_schema_format(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["response_format"]["type"] == "json_schema"
            assert call_kwargs["response_format"]["json_schema"]["strict"] is True

    @pytest.mark.parametrize(
        "model,flex,expected_tier,expected_effort,expected_timeout",
        [
            (OpenAIModel.GPT_5_NANO, True, "flex", "minimal", SUMMARIZATION_FLEX_TIMEOUT),
            (OpenAIModel.GPT_5_NANO, False, None, "minimal", SUMMARIZATION_TIMEOUT),
            (OpenAIModel.GPT_4_1_MINI, True, None, None, SUMMARIZATION_TIMEOUT),
        ],
    )
    def test_service_tier_and_reasoning_effort_selection(
        self, valid_response_json, model, flex, expected_tier, expected_effort, expected_timeout
    ):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=model,
                flex=flex,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs.get("service_tier") == expected_tier
            assert call_kwargs.get("reasoning_effort") == expected_effort
            assert call_kwargs["timeout"] == expected_timeout

    def test_flex_rate_limit_falls_back_to_standard_tier(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [_rate_limit_error(), mock_response]

            result = summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_5_NANO,
                flex=True,
            )

            assert isinstance(result, SummarizationResponse)
            assert mock_client.chat.completions.create.call_count == 2
            retry_kwargs = mock_client.chat.completions.create.call_args_list[1][1]
            assert "service_tier" not in retry_kwargs
            assert retry_kwargs["timeout"] == SUMMARIZATION_TIMEOUT

    def test_standard_tier_rate_limit_does_not_retry(self, valid_response_json):
        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.side_effect = _rate_limit_error()

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_5_NANO,
                    flex=False,
                )

            assert mock_client.chat.completions.create.call_count == 1
