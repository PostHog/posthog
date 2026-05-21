import ssl
from datetime import timedelta

import pytest

import httpx
import aiohttp
from google.genai import errors as genai_errors
from temporalio.exceptions import ApplicationError

from posthog.temporal.session_replay.session_summary.activities.video_based.gemini_retry import (
    raise_retryable_for_transient_gemini_error,
)


def _genai_server_error(message: str = "unavailable", code: int = 503) -> genai_errors.ServerError:
    return genai_errors.ServerError(
        code=code,
        response_json={"error": {"code": code, "status": "UNAVAILABLE", "message": message}},
    )


def _genai_client_error(message: str, code: int) -> genai_errors.ClientError:
    return genai_errors.ClientError(
        code=code,
        response_json={"error": {"code": code, "status": "FAILED_PRECONDITION", "message": message}},
    )


@pytest.mark.parametrize(
    "exc_factory",
    [
        # Gemini server-side errors (5xx)
        lambda: _genai_server_error("UNAVAILABLE", code=503),
        lambda: _genai_server_error("Deadline expired", code=504),
        lambda: _genai_server_error("This model is currently experiencing high demand", code=503),
        lambda: _genai_server_error("Failed to convert server response to JSON", code=500),
        # Transient 4xx that we treat as retryable
        lambda: _genai_client_error("Resource exhausted", code=429),
        lambda: _genai_client_error("Request timeout", code=408),
        # httpx transport errors (sync upload path)
        lambda: httpx.RemoteProtocolError("Server disconnected without sending a response"),
        lambda: httpx.ReadError("WRONG_VERSION_NUMBER"),
        lambda: httpx.ProxyError("504 Gateway timeout"),
        # aiohttp transport errors (async generate_content path)
        lambda: aiohttp.ClientPayloadError("TransferEncodingError"),
        lambda: aiohttp.ServerDisconnectedError("Server disconnected"),
        # Raw socket-level resets
        lambda: ConnectionResetError("Connection reset by peer"),
        lambda: BrokenPipeError("Broken pipe"),
        # SSL bundle load failures during client init
        lambda: ssl.SSLError("[X509] PEM lib"),
    ],
)
def test_transient_errors_raise_retryable_application_error(exc_factory):
    exc = exc_factory()
    with pytest.raises(ApplicationError) as exc_info:
        try:
            raise exc
        except BaseException as e:
            raise_retryable_for_transient_gemini_error(e, context="unit_test")

    assert exc_info.value.type == "GeminiTransientError"
    assert exc_info.value.non_retryable is False
    assert exc_info.value.next_retry_delay is not None


def test_non_transient_genai_client_error_is_not_reraised():
    # 400 (invalid argument) should not be retried — the caller's bare `raise` propagates it.
    exc = _genai_client_error("INVALID_ARGUMENT", code=400)
    raise_retryable_for_transient_gemini_error(exc, context="unit_test")  # no-op


def test_arbitrary_exception_is_not_reraised():
    # ValueError isn't transient — helper must not reclassify it.
    raise_retryable_for_transient_gemini_error(ValueError("bad input"), context="unit_test")


def test_next_retry_delay_is_respected():
    custom_delay = timedelta(seconds=120)
    with pytest.raises(ApplicationError) as exc_info:
        raise_retryable_for_transient_gemini_error(
            _genai_server_error(),
            context="unit_test",
            next_retry_delay=custom_delay,
        )
    assert exc_info.value.next_retry_delay == custom_delay
