import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

import pytest
from unittest import TestCase
from unittest.mock import MagicMock, patch

import httpx
import openai
from parameterized import parameterized
from pydantic import BaseModel
from temporalio.exceptions import CancelledError

from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import PinnedUrlVerdict

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    LLMError,
    ProviderConfigurationError,
    ProviderRequestRejectedError,
    ProviderTimeoutError,
    QuotaExceededError,
)
from products.ai_observability.backend.llm.providers import openai_compatible
from products.ai_observability.backend.llm.providers.openai_compatible import (
    DISALLOWED_BASE_URL_MESSAGE,
    REDIRECT_MESSAGE,
    VALIDATION_TIMEOUT,
    OpenAICompatibleAdapter,
    error_field_for_validation_message,
    is_allowed_custom_base_url,
)
from products.ai_observability.backend.llm.types import AnalyticsContext, CompletionRequest

# A public IP literal keeps the DNS-resolution check offline in tests.
ALLOWED_BASE_URL = "https://8.8.8.8/v1"

OPENAI_PATCH_TARGET = "products.ai_observability.backend.llm.providers.openai_compatible.openai.OpenAI"


def _completion_request() -> CompletionRequest:
    return CompletionRequest(
        model="some-model",
        messages=[{"role": "user", "content": "hi"}],
        provider="openai_compatible",
    )


class TestIsAllowedCustomBaseUrl:
    @parameterized.expand(
        [
            ("empty", ""),
            ("no_hostname", "https://"),
            ("http_scheme", "http://8.8.8.8/v1"),
            ("private_ip", "https://10.0.0.1/v1"),
            ("loopback", "https://127.0.0.1/v1"),
            ("cloud_metadata", "https://169.254.169.254/latest"),
            ("ipv6_loopback", "https://[::1]/v1"),
        ]
    )
    def test_disallowed_base_urls(self, _name, base_url):
        assert is_allowed_custom_base_url(base_url) is False

    def test_public_https_base_url_is_allowed(self):
        assert is_allowed_custom_base_url(ALLOWED_BASE_URL) is True


class TestErrorFieldForValidationMessage:
    @parameterized.expand(
        [
            ("required", "Base URL is required", "base_url"),
            ("disallowed", DISALLOWED_BASE_URL_MESSAGE, "base_url"),
            ("not_found", "The endpoint did not return a model list, check the base URL", "base_url"),
            ("redirect", REDIRECT_MESSAGE, "base_url"),
            ("connection", "Could not connect to the endpoint", "base_url"),
            ("response_limit", openai_compatible.RESPONSE_LIMIT_MESSAGE, "base_url"),
            ("timeout", str(ProviderTimeoutError(VALIDATION_TIMEOUT)), "base_url"),
            ("bad_key", "Invalid API key", "api_key"),
            ("unattributed", "Rate limited, please try again later", None),
            ("none", None, None),
        ]
    )
    def test_maps_message_to_field(self, _name, message, expected_field):
        assert error_field_for_validation_message(message) == expected_field


class TestPinnedHttpClient:
    def test_client_is_locked_to_the_validated_endpoint(self):
        with openai_compatible._pinned_http_client(ALLOWED_BASE_URL, VALIDATION_TIMEOUT) as client:
            # Following a redirect would reach a host nothing validated, and the hop would be
            # made by the pooled connection rather than a freshly validated one.
            assert client.follow_redirects is False

            with pytest.raises(SSRFBlockedError):
                client.get("https://internal.example/v1/models")


class TestOpenAICompatibleAdapter:
    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_uses_configured_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)

        assert state == "ok"
        assert message is None
        assert mock_openai.call_args.kwargs["base_url"] == ALLOWED_BASE_URL
        # Listing is cheap, and the endpoint is user-configured: inheriting the completion
        # timeout would let a stalling host hold a synchronous worker for five minutes.
        assert mock_openai.call_args.kwargs["timeout"] == VALIDATION_TIMEOUT
        assert mock_openai.call_args.kwargs["max_retries"] == 0

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_without_base_url_is_invalid(self, mock_openai):
        state, message = OpenAICompatibleAdapter.validate_key("test-key")

        assert state == "invalid"
        assert message == "Base URL is required"
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_with_disallowed_base_url_is_invalid(self, mock_openai):
        state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url="https://10.0.0.1/v1")

        assert state == "invalid"
        assert message == DISALLOWED_BASE_URL_MESSAGE
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_uses_configured_base_url(self, mock_openai):
        model = MagicMock()
        model.id = "qwen3-max"
        model.created = 1700000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model]
        mock_openai.return_value = mock_client

        models = OpenAICompatibleAdapter.list_models("test-key", base_url=ALLOWED_BASE_URL)

        assert models == ["qwen3-max"]
        assert mock_openai.call_args.kwargs["base_url"] == ALLOWED_BASE_URL

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_handles_endpoints_that_omit_created(self, mock_openai):
        # Endpoints are free to leave `created` out, and the SDK turns that into None. Sorting
        # those raises a TypeError that the adapter would swallow into an empty model list.
        undated, dated = MagicMock(), MagicMock()
        undated.id, undated.created = "no-timestamp", None
        dated.id, dated.created = "timestamped", 1700000000
        mock_openai.return_value.models.list.return_value = [undated, dated]

        assert OpenAICompatibleAdapter.list_models("test-key", base_url=ALLOWED_BASE_URL) == [
            "timestamped",
            "no-timestamp",
        ]

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_without_key_returns_empty(self, mock_openai):
        assert OpenAICompatibleAdapter.list_models(None, base_url=ALLOWED_BASE_URL) == []
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_with_disallowed_base_url_returns_empty(self, mock_openai):
        assert OpenAICompatibleAdapter.list_models("test-key", base_url="https://169.254.169.254/v1") == []
        mock_openai.assert_not_called()

    @parameterized.expand(
        [
            ("unconfigured", ""),
            ("private_ip", "https://10.0.0.1/v1"),
        ]
    )
    def test_complete_refuses_disallowed_base_url(self, _name, base_url):
        adapter = OpenAICompatibleAdapter(base_url=base_url)

        with pytest.raises(ProviderConfigurationError, match="Base URL must be"):
            adapter.complete(_completion_request(), "test-key", AnalyticsContext())

    def test_stream_refuses_disallowed_base_url(self):
        adapter = OpenAICompatibleAdapter(base_url="")

        with pytest.raises(ProviderConfigurationError, match="Base URL must be"):
            list(adapter.stream(_completion_request(), "test-key", AnalyticsContext()))

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_reports_a_redirect_instead_of_following_it(self, mock_openai):
        redirect = openai.APIStatusError(
            "redirect",
            response=httpx.Response(302, request=httpx.Request("GET", f"{ALLOWED_BASE_URL}/models")),
            body=None,
        )
        mock_openai.return_value.models.list.side_effect = redirect

        state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)

        assert state == "invalid"
        assert message == REDIRECT_MESSAGE

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_is_invalid_when_the_endpoint_fails_validation(self, mock_openai):
        # Validation runs while the client is built, so a URL that fails it is reported as an
        # invalid key rather than escaping as a 500. A rebind *after* this point is handled by
        # dialing the pinned address, not by this path.
        with patch.object(
            openai_compatible,
            "validate_url_and_pin_ips",
            return_value=PinnedUrlVerdict(allowed=False, reason="Internal IP", pinned_ips=set()),
        ):
            state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)

        assert state == "invalid"
        assert message == DISALLOWED_BASE_URL_MESSAGE
        mock_openai.assert_not_called()

    def test_list_models_is_empty_when_the_endpoint_fails_validation(self):
        with patch.object(
            openai_compatible,
            "validate_url_and_pin_ips",
            return_value=PinnedUrlVerdict(allowed=False, reason="Internal IP", pinned_ips=set()),
        ):
            assert OpenAICompatibleAdapter.list_models("test-key", base_url=ALLOWED_BASE_URL) == []

    @patch(OPENAI_PATCH_TARGET)
    def test_complete_without_api_key_raises(self, mock_openai):
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)

        with pytest.raises(ValueError, match="BYOK-only"):
            adapter.complete(_completion_request(), None, AnalyticsContext())
        mock_openai.assert_not_called()


class _Verdict(BaseModel):
    verdict: bool


class _ResponseBody(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], clock: list[float] | None = None) -> None:
        self.chunks = chunks
        self.clock = clock
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            if self.clock is not None:
                self.clock[0] += 1
            yield chunk

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self:
            yield chunk

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.close()


@contextmanager
def _mock_response(body: _ResponseBody, headers: dict[str, str] | None = None) -> Iterator[None]:
    response = httpx.Response(200, stream=body, headers=headers or {})
    with (
        patch("httpx.HTTPTransport.handle_request", return_value=response),
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
    ):
        try:
            yield
        finally:
            assert body.closed


@contextmanager
def _response_over_limit(response_kind: str) -> Iterator[None]:
    body = _ResponseBody([b"x" * 8192] * 129 if response_kind == "oversized" else [b"compressed"])
    headers = {"Content-Encoding": "gzip"} if response_kind == "compressed" else {}
    with _mock_response(body, headers):
        yield


@contextmanager
def _dripping_response(adapter: OpenAICompatibleAdapter) -> Iterator[None]:
    clock = [0.0]
    body = _ResponseBody([b" "] * 4, clock)
    with (
        patch.object(adapter, "request_timeout", 2.0),
        patch.object(openai_compatible, "VALIDATION_TIMEOUT", 2.0),
        patch("asyncio.BaseEventLoop.time", side_effect=lambda: clock[0]),
        _mock_response(body, {"Content-Type": "application/json"}),
    ):
        yield


class TestOpenAICompatibleRequestBounds(TestCase):
    @parameterized.expand([("oversized",), ("compressed",)])
    def test_complete_rejects_unbounded_responses(self, response_kind: str) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        request = _completion_request()
        request.response_format = _Verdict
        with _response_over_limit(response_kind), pytest.raises(ProviderRequestRejectedError) as error:
            adapter.complete(request, "test-key", AnalyticsContext(capture=False))
        assert str(error.value) == openai_compatible.RESPONSE_LIMIT_MESSAGE

    @parameterized.expand([("oversized",), ("compressed",)])
    def test_stream_reports_response_limit(self, response_kind: str) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        with _response_over_limit(response_kind):
            chunks = list(adapter.stream(_completion_request(), "test-key", AnalyticsContext(capture=False)))
        assert [(chunk.type, chunk.data) for chunk in chunks] == [
            ("error", {"error": openai_compatible.RESPONSE_LIMIT_MESSAGE})
        ]

    @parameterized.expand([("oversized",), ("compressed",)])
    def test_validate_key_reports_response_limit(self, response_kind: str) -> None:
        with _response_over_limit(response_kind):
            result = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)
        assert result == ("invalid", openai_compatible.RESPONSE_LIMIT_MESSAGE)

    @parameterized.expand([("oversized",), ("compressed",)])
    def test_list_models_logs_response_limit(self, response_kind: str) -> None:
        with _response_over_limit(response_kind), self.assertLogs(openai_compatible.logger) as logs:
            assert OpenAICompatibleAdapter.list_models("test-key", base_url=ALLOWED_BASE_URL) == []
        assert logs.records[0].exc_info is not None
        error = logs.records[0].exc_info[1]
        assert isinstance(error, openai.APIConnectionError)
        assert isinstance(error.__cause__, httpx.DecodingError)

    @parameterized.expand([("complete", False), ("complete", True), ("stream", False), ("stream", True)])
    def test_preserves_cancellation_without_retrying(self, operation: str, capture: bool) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        request = _completion_request()
        request.response_format = _Verdict
        with (
            patch("httpx.HTTPTransport.handle_request", side_effect=CancelledError) as sync_send,
            patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=CancelledError) as async_send,
            patch("posthoganalytics.default_client", MagicMock()),
            pytest.raises(CancelledError),
        ):
            if operation == "complete":
                adapter.complete(request, "test-key", AnalyticsContext(capture=capture))
            else:
                list(adapter.stream(request, "test-key", AnalyticsContext(capture=capture)))
        assert sync_send.call_count + async_send.call_count == 1

    def test_complete_stops_at_total_deadline(self) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        with _dripping_response(adapter), pytest.raises(ProviderTimeoutError, match="within 2 seconds"):
            adapter.complete(_completion_request(), "test-key", AnalyticsContext(capture=False))

    def test_stream_reports_total_deadline(self) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        with _dripping_response(adapter):
            chunks = list(adapter.stream(_completion_request(), "test-key", AnalyticsContext(capture=False)))
        assert [(chunk.type, chunk.data) for chunk in chunks] == [("error", {"error": str(ProviderTimeoutError(2))})]

    def test_validate_key_reports_total_deadline(self) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        with _dripping_response(adapter):
            result = adapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)
        assert result == ("error", str(ProviderTimeoutError(2)))

    def test_list_models_logs_total_deadline(self) -> None:
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)
        with _dripping_response(adapter), self.assertLogs(openai_compatible.logger) as logs:
            assert adapter.list_models("test-key", base_url=ALLOWED_BASE_URL) == []
        assert logs.records[0].exc_info is not None
        error = logs.records[0].exc_info[1]
        assert isinstance(error, openai.APIConnectionError)
        assert isinstance(error.__cause__, httpx.TimeoutException)

    @parameterized.expand(
        [
            (401, {"message": "Invalid API key"}, AuthenticationError),
            (429, {"message": "Quota exceeded", "code": "insufficient_quota"}, QuotaExceededError),
        ]
    )
    def test_complete_preserves_permanent_errors(
        self, status: int, error_body: dict[str, str], expected_error: type[LLMError]
    ) -> None:
        response = httpx.Response(status, stream=httpx.ByteStream(json.dumps({"error": error_body}).encode()))
        with (
            patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
            pytest.raises(expected_error),
        ):
            OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL).complete(
                _completion_request(), "test-key", AnalyticsContext(capture=False)
            )

    def test_structured_output_falls_back_without_sdk_retries(self) -> None:
        fallback_body = _ResponseBody(
            [
                json.dumps(
                    {
                        "id": "fixture",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "some-model",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": '{"verdict": true}'},
                            }
                        ],
                    }
                ).encode()
            ]
        )
        responses = [
            httpx.Response(
                400,
                stream=_ResponseBody([b'{"error":{"message":"response_format json_schema is not supported"}}']),
                headers={"Content-Type": "application/json"},
            ),
            httpx.Response(200, stream=fallback_body, headers={"Content-Type": "application/json"}),
        ]
        request = _completion_request()
        request.response_format = _Verdict

        with patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=responses) as send:
            result = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL).complete(
                request, "test-key", AnalyticsContext(capture=False)
            )

        assert result.parsed == _Verdict(verdict=True)
        assert send.call_count == 2
        assert fallback_body.closed

    def test_closing_stream_closes_the_connection(self) -> None:
        payload = json.dumps(
            {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "some-model",
                "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
            }
        ).encode()
        body = _ResponseBody([b"data: " + payload + b"\n\n", b"data: [DONE]\n\n"])
        response = httpx.Response(200, stream=body, headers={"Content-Type": "text/event-stream"})
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)

        with (
            patch("httpx.HTTPTransport.handle_request", return_value=response),
            patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        ):
            stream = adapter.stream(_completion_request(), "test-key", AnalyticsContext(capture=False))
            assert next(stream).data == {"text": "hello"}
            stream.close()

        assert body.closed
