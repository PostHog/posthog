from collections.abc import Callable

import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai
from parameterized import parameterized
from posthoganalytics.ai.openai import (
    AzureOpenAI as WrappedAzureOpenAI,
    OpenAI as WrappedOpenAI,
)
from pydantic import BaseModel, ValidationError, model_validator

from products.ai_observability.backend.llm.errors import (
    ContextWindowExceededError,
    QuotaExceededError,
    StructuredOutputParseError,
)
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
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=True, privacy_mode=True)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {
            "posthog_distinct_id": "user-1",
            "posthog_trace_id": "trace-1",
            "posthog_properties": {},
            "posthog_groups": {},
            "posthog_privacy_mode": True,
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


class _VerdictWithNA(BaseModel):
    applicable: bool
    verdict: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> "_VerdictWithNA":
        if self.applicable and self.verdict is None:
            raise ValueError("verdict is required when applicable is true")
        return self


def _length_finish_reason_error() -> openai.LengthFinishReasonError:
    return openai.LengthFinishReasonError(completion=MagicMock(usage=None))


def _cross_field_error() -> ValidationError:
    try:
        _VerdictWithNA.model_validate({"applicable": True, "verdict": None})
    except ValidationError as e:
        return e
    raise AssertionError("expected ValidationError")


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

    @parameterized.expand(
        [
            ("length_finish_reason", _length_finish_reason_error),
            ("cross_field_validator", _cross_field_error),
        ]
    )
    def test_structured_output_parse_errors_map_to_parse_error(
        self, _name: str, make_error: Callable[[], Exception]
    ) -> None:
        adapter = OpenAIAdapter()
        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = make_error()
        request = CompletionRequest(
            model="gpt-5-mini",
            system="s",
            messages=[{"role": "user", "content": "x"}],
            provider="openai",
            response_format=_Verdict,
        )

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            with pytest.raises(StructuredOutputParseError):
                adapter.complete(request, api_key="sk-test", analytics=AnalyticsContext(capture=False))


class TestOpenAIStreamErrorSurfacing:
    def test_model_404_yields_actionable_message_instead_of_raw_sdk_text(self):
        # Streaming has no exception channel, so this chunk is the entire explanation the user
        # gets in the playground.
        request = CompletionRequest(
            model="gpt-4-turbo-2024-04-09",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="openai",
        )
        http_request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        response = httpx.Response(status_code=404, request=http_request, json={"error": {"message": "does not exist"}})
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.NotFoundError(
            "Error code: 404 - the model `gpt-4-turbo-2024-04-09` does not exist",
            response=response,
            body=None,
        )

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            chunks = list(OpenAIAdapter().stream(request, api_key="sk-test", analytics=AnalyticsContext(capture=False)))

        errors = [chunk.data["error"] for chunk in chunks if chunk.type == "error"]
        assert errors == ["Model 'gpt-4-turbo-2024-04-09' is not available. Pick a different model and try again."]
        assert "Error code: 404" not in errors[0]

    def test_unmapped_400_keeps_the_providers_reason_instead_of_telling_the_user_to_retry(self):
        # An unsupported parameter is the most common way a playground run fails, and it has no
        # branch in the taxonomy. "Try again" would be advice that cannot work, so the provider's
        # sentence has to come through — without the SDK's `Error code: 400 - {...}` wrapper.
        request = CompletionRequest(
            model="gpt-5",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="openai",
        )
        detail = "Unsupported value: 'temperature' does not support 0.7 with this model."
        body = {"error": {"message": detail}}
        http_request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.BadRequestError(
            f"Error code: 400 - {body}",
            response=httpx.Response(status_code=400, request=http_request, json=body),
            body=body,
        )

        with patch("products.ai_observability.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            chunks = list(OpenAIAdapter().stream(request, api_key="sk-test", analytics=AnalyticsContext(capture=False)))

        errors = [chunk.data["error"] for chunk in chunks if chunk.type == "error"]
        assert len(errors) == 1
        assert detail in errors[0]
        assert "Error code: 400" not in errors[0]
