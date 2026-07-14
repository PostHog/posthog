import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai
from parameterized import parameterized
from posthoganalytics.ai.openai import (
    AzureOpenAI as WrappedAzureOpenAI,
    OpenAI as WrappedOpenAI,
)
from pydantic import BaseModel

from products.ai_observability.backend.llm.errors import ContextWindowExceededError, QuotaExceededError
from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.ai_observability.backend.llm.types import AnalyticsContext, CompletionRequest


class TestOpenAIRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert OpenAIAdapter.recommended_models() == set(OpenAIConfig.SUPPORTED_MODELS)


def _api_model(model_id: str, created: int) -> MagicMock:
    model = MagicMock()
    model.id = model_id
    model.created = created
    return model


class TestOpenAIListModels:
    @parameterized.expand(sorted(OpenAIConfig.RESPONSES_ONLY_MODELS))
    def test_responses_only_model_is_not_picker_eligible(self, model: str):
        assert model not in OpenAIConfig.SUPPORTED_MODELS
        assert model not in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING

    def test_list_models_without_key_returns_supported_models(self):
        assert OpenAIAdapter.list_models() == OpenAIConfig.SUPPORTED_MODELS

    def test_list_models_excludes_responses_only_models_from_api_discovery(self):
        api_models = [
            _api_model("o3-pro", 300),
            _api_model("gpt-5-pro", 200),
            _api_model("gpt-6-future", 100),
        ]
        mock_client = MagicMock()
        mock_client.models.list.return_value = api_models

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            result = OpenAIAdapter.list_models(api_key="sk-test")

        assert "gpt-6-future" in result
        assert OpenAIConfig.RESPONSES_ONLY_MODELS.isdisjoint(result)


class TestBuildAnalyticsKwargs:
    @parameterized.expand(
        [
            ("wrapped_openai", WrappedOpenAI),
            ("wrapped_azure_openai", WrappedAzureOpenAI),
        ]
    )
    def test_wrapped_clients_get_analytics_kwargs_when_capture_enabled(self, _name, client_cls):
        adapter = OpenAIAdapter()
        client = MagicMock(spec=client_cls)
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=True)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {
            "posthog_distinct_id": "user-1",
            "posthog_trace_id": "trace-1",
            "posthog_properties": {},
            "posthog_groups": {},
        }

    def test_capture_disabled_returns_empty_kwargs(self):
        adapter = OpenAIAdapter()
        client = MagicMock(spec=WrappedOpenAI)
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=False)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {}

    def test_unknown_client_returns_empty_kwargs(self):
        """A non-wrapped client (e.g. raw openai.OpenAI) should not receive analytics kwargs."""
        adapter = OpenAIAdapter()
        client = MagicMock()  # no spec — not an instance of Wrapped*
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=True)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {}


def _make_api_status_error(status_code: int, message: str) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status_code=status_code, request=request, json={"error": {"message": message}})
    return openai.APIStatusError(message, response=response, body={"error": {"message": message, "code": status_code}})


def _make_bad_request_error(message: str) -> openai.BadRequestError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status_code=400, request=request, json={"error": {"message": message}})
    return openai.BadRequestError(message, response=response, body={"error": {"message": message}})


class _Verdict(BaseModel):
    verdict: bool


class TestOpenAIAdapterErrorMapping:
    @pytest.fixture
    def request_no_structured_output(self) -> CompletionRequest:
        return CompletionRequest(
            model="gpt-4.1",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="openai",
        )

    def test_402_is_mapped_to_quota_exceeded(self, request_no_structured_output: CompletionRequest):
        adapter = OpenAIAdapter()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _make_api_status_error(
            402, "This request requires more credits, or fewer max_tokens."
        )

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            with pytest.raises(QuotaExceededError, match="credits"):
                adapter.complete(
                    request_no_structured_output, api_key="sk-test", analytics=AnalyticsContext(capture=False)
                )

    def test_non_402_status_error_is_not_swallowed(self, request_no_structured_output: CompletionRequest):
        adapter = OpenAIAdapter()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _make_api_status_error(500, "server error")

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            with pytest.raises(openai.APIStatusError):
                adapter.complete(
                    request_no_structured_output, api_key="sk-test", analytics=AnalyticsContext(capture=False)
                )

    @parameterized.expand(
        [
            (
                "openai_context_length_exceeded",
                "Error code: 400 - {'error': {'message': 'Input tokens exceed the configured limit of 272000 "
                "tokens. Your messages resulted in 300826 tokens. Please reduce the length of the messages.', "
                "'code': 'context_length_exceeded'}}",
            ),
            (
                "openrouter_prompt_too_long",
                "Error code: 400 - {'error': {'message': 'prompt is too long: 212618 tokens > 200000 maximum'}}",
            ),
        ]
    )
    def test_structured_context_window_400_maps_to_context_window_exceeded(self, _name: str, message: str):
        adapter = OpenAIAdapter()
        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = _make_bad_request_error(message)
        request = CompletionRequest(
            model="gpt-5-mini",
            system="s",
            messages=[{"role": "user", "content": "x"}],
            provider="openai",
            response_format=_Verdict,
        )

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            with pytest.raises(ContextWindowExceededError):
                adapter.complete(request, api_key="sk-test", analytics=AnalyticsContext(capture=False))
