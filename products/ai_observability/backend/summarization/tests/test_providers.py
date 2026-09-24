import json

import pytest
from unittest.mock import MagicMock, patch

import httpx
from openai import APIConnectionError, APIStatusError, BadRequestError, InternalServerError, RateLimitError, omit
from rest_framework import exceptions

from products.ai_observability.backend.summarization.constants import SUMMARIZATION_FLEX_TIMEOUT, SUMMARIZATION_TIMEOUT
from products.ai_observability.backend.summarization.llm.openai import summarize_with_openai
from products.ai_observability.backend.summarization.llm.schema import SummarizationResponse
from products.ai_observability.backend.summarization.models import OpenAIModel, SummarizationMode

_REQUEST = httpx.Request("POST", "https://example.com/v1/chat/completions")


def _rate_limit_error() -> RateLimitError:
    return RateLimitError("rate limited", response=httpx.Response(429, request=_REQUEST), body=None)


def _flex_408_error() -> APIStatusError:
    # OpenAI answers a server-side flex timeout with 408, which the SDK raises as the bare
    # APIStatusError because it has no named class for that status.
    return APIStatusError("request timeout", response=httpx.Response(408, request=_REQUEST), body=None)


def _gateway_ceiling_error() -> InternalServerError:
    # The ai-gateway answers 504 when a buffered call outlives its ~290s response ceiling.
    return InternalServerError("gateway timeout", response=httpx.Response(504, request=_REQUEST), body=None)


def _json_body_parse_error() -> BadRequestError:
    # OpenAI reports a request body it could not read as a 400 that names the JSON body.
    return BadRequestError(
        "We could not parse the JSON body of your request.",
        response=httpx.Response(400, request=_REQUEST),
        body=None,
    )


def _connection_error() -> APIConnectionError:
    # A proxy or LB resetting a long-parked flex request surfaces as the bare parent class,
    # not APITimeoutError, so the fallback must catch APIConnectionError itself.
    return APIConnectionError(request=_REQUEST)


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
            mock_client.with_options.return_value = mock_client
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
            mock_client.with_options.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    @pytest.mark.parametrize(
        "error,expected_detail",
        [
            (Exception("API Error"), "Failed to generate summary"),
            (_rate_limit_error(), "Failed to generate summary (the model provider returned 429)"),
            (_json_body_parse_error(), "Failed to generate summary (the model provider returned 400)"),
            (_connection_error(), "Failed to generate summary (we could not reach the model provider)"),
        ],
    )
    def test_api_error_detail_carries_the_provider_failure(self, error, expected_detail):
        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
            mock_client.chat.completions.create.side_effect = error

            with pytest.raises(exceptions.APIException) as raised:
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

            assert str(raised.value.detail) == expected_detail

    def test_api_error_is_captured_with_a_status_specific_fingerprint(self):
        with (
            patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client,
            patch("products.ai_observability.backend.summarization.llm.openai.capture_exception") as mock_capture,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
            mock_client.chat.completions.create.side_effect = _json_body_parse_error()

            with pytest.raises(exceptions.APIException):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

            properties = mock_capture.call_args[1]["additional_properties"]
            assert properties["$exception_fingerprint"] == "aio_summarization.BadRequestError.400"
            assert properties["provider_status"] == 400

    def test_uses_correct_model(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
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
            mock_client.with_options.return_value = mock_client
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
            mock_client.with_options.return_value = mock_client
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
            mock_client.with_options.return_value = mock_client
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
            (OpenAIModel.GPT_5_NANO, False, omit, "minimal", SUMMARIZATION_TIMEOUT),
            # gpt-4.1 rejects service_tier, so a flex request must not forward it
            (OpenAIModel.GPT_4_1_MINI, True, omit, omit, SUMMARIZATION_TIMEOUT),
        ],
    )
    def test_flex_and_reasoning_effort_apply_only_to_gpt5(
        self, valid_response_json, model, flex, expected_tier, expected_effort, expected_timeout
    ):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
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
            if expected_tier == "flex":
                # The flex attempt must not inherit the SDK's default retries; the standard
                # tier is its retry (see the budget math at the call site).
                mock_client.with_options.assert_called_once_with(max_retries=0)

    @pytest.mark.parametrize(
        "flex_error",
        [
            _rate_limit_error(),
            _connection_error(),
            _gateway_ceiling_error(),
            _flex_408_error(),
            _json_body_parse_error(),
        ],
    )
    def test_flex_failure_falls_back_to_standard_tier(self, valid_response_json, flex_error):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [flex_error, mock_response]

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
            assert retry_kwargs.get("service_tier") == omit
            assert retry_kwargs["timeout"] == SUMMARIZATION_TIMEOUT

    def test_flex_config_error_does_not_fall_back(self, valid_response_json):
        # A 400 (bad request) on flex is a configuration bug the standard tier shares; falling
        # back would mask it, so it must propagate instead.
        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
            mock_client.chat.completions.create.side_effect = BadRequestError(
                "Invalid schema for response_format", response=httpx.Response(400, request=_REQUEST), body=None
            )

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_5_NANO,
                    flex=True,
                )

            assert mock_client.chat.completions.create.call_count == 1

    def test_standard_tier_rate_limit_does_not_retry(self):
        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.with_options.return_value = mock_client
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
