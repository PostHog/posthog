import json
import asyncio
from collections.abc import Iterator
from contextlib import nullcontext
from ipaddress import ip_address

import pytest
from unittest.mock import patch

import httpx
import httpcore

from posthog.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    RefusalAnswer,
    ScoreAnswer,
    ScoreQuestion,
)

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    ProviderRequestRejectedError,
    QuotaExceededError,
    RetryableRateLimitError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.llm.providers.openai_decisions import OpenAIDecisionAdapter


@pytest.fixture(autouse=True)
def pin_endpoint() -> Iterator[None]:
    with patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("8.8.8.8")}):
        yield


def _json_response(status: int, payload: object, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": "application/json", **(headers or {})},
        stream=httpx.ByteStream(json.dumps(payload).encode()),
    )


def test_native_questions_and_answers() -> None:
    questions: dict[str, Question] = {
        "verdict": NoulQuestion(
            instructions="Is the reply helpful?", criteria_true="Helpful", criteria_false="Unhelpful"
        ),
        "category": ChoiceQuestion(
            instructions="Classify the reply.", criteria={"resolved": "Solved", "other": "Other"}
        ),
        "score": ScoreQuestion(instructions="Rate the reply.", criteria=["Poor", "Good", "Excellent"]),
        "applicable": NoulQuestion(instructions="Are the criteria relevant?"),
    }
    response = _json_response(
        200,
        payload={
            "model": "gpt-6-luna",
            "answers": [
                {
                    "name": "score",
                    "type": "score",
                    "score": 1.5,
                    "confidence": 0.5,
                    "probabilities": [
                        {"value": 0, "label": "0", "probability": 0},
                        {"value": 1, "label": "1", "probability": 0.5},
                        {"value": 2, "label": "2", "probability": 0.5},
                    ],
                },
                {
                    "name": "category",
                    "type": "choice",
                    "choice": "resolved",
                    "confidence": 0.8,
                    "probabilities": [
                        {"value": "resolved", "probability": 0.8},
                        {"value": "other", "probability": 0.2},
                    ],
                },
                {"name": "verdict", "type": "predicate", "probability": 0.7},
                {"name": "applicable", "type": "refusal"},
            ],
            "usage": {"input_tokens": 120, "output_tokens": 0},
        },
    )
    with patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response) as transport:
        result = OpenAIDecisionAdapter().evaluate(
            api_key="example-token", model="gpt-6-luna", state="Hello!", questions=questions
        )

    request = transport.call_args.args[0]
    assert str(request.url) == "https://api.openai.com/v1/decisions"
    assert request.headers["Authorization"] == "Bearer example-token"
    sent = json.loads(request.content)
    assert sent["input"] == "Hello!"
    assert sent["model"] == "gpt-6-luna"
    assert sent["questions"] == [
        {
            "name": "verdict",
            "type": "predicate",
            "instructions": "Is the reply helpful?\nTrue: Helpful\nFalse: Unhelpful",
        },
        {
            "name": "category",
            "type": "choice",
            "instructions": "Classify the reply.",
            "choices": [
                {"value": "resolved", "description": "Solved"},
                {"value": "other", "description": "Other"},
            ],
        },
        {
            "name": "score",
            "type": "score",
            "instructions": "Rate the reply.",
            "levels": [
                {"label": "0", "description": "Poor"},
                {"label": "1", "description": "Good"},
                {"label": "2", "description": "Excellent"},
            ],
        },
        {"name": "applicable", "type": "predicate", "instructions": "Are the criteria relevant?"},
    ]
    assert result.answers["verdict"] == NoulAnswer(probability=0.7)
    assert result.answers["category"] == ChoiceAnswer(
        choice="resolved", confidence=0.8, probabilities={"resolved": 0.8, "other": 0.2}
    )
    assert result.answers["score"] == ScoreAnswer(score=1.5, confidence=0.5, probabilities={"0": 0, "1": 0.5, "2": 0.5})
    assert isinstance(result.answers["applicable"], RefusalAnswer)
    assert (result.input_tokens, result.output_tokens) == (120, 0)


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [{"name": "other", "type": "predicate", "probability": 0.9}],
        [{"name": "verdict", "type": "predicate", "probability": 0.9}] * 2,
        [{"name": "verdict", "type": "predicate", "probability": True}],
        [{"name": "verdict", "type": "predicate", "probability": "0.9"}],
        [{"name": "verdict", "type": "predicate", "probability": 1.1}],
        [{"name": "verdict", "type": "noul", "noul": 0.9}],
        [{"name": "verdict", "type": "choice", "choice": "true", "confidence": 1, "probabilities": []}],
    ],
)
def test_invalid_answers_are_rejected(answers: object) -> None:
    response = _json_response(200, payload={"model": "gpt-6-luna", "answers": answers})
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        OpenAIDecisionAdapter().evaluate(
            api_key="example-token",
            model="gpt-6-luna",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is this a greeting?")},
        )


def test_invalid_json_is_a_structured_output_error() -> None:
    response = httpx.Response(200, headers={"Content-Type": "application/json"}, stream=httpx.ByteStream(b"{"))
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        OpenAIDecisionAdapter().evaluate(
            api_key="example-token",
            model="gpt-6-luna",
            state="Example reply.",
            questions={"verdict": NoulQuestion(instructions="Is this a greeting?")},
        )


@pytest.mark.parametrize("values", [[0, 0, 2], [0, 1, 3], [False, 1, 2], [0.0, 1, 2]])
def test_native_score_probabilities_keep_integer_level_identity(values: list[object]) -> None:
    response = _json_response(
        200,
        payload={
            "model": "gpt-6-luna",
            "answers": [
                {
                    "name": "score",
                    "type": "score",
                    "score": 1.5,
                    "confidence": 0.5,
                    "probabilities": [{"value": value, "label": str(value), "probability": 0.5} for value in values],
                }
            ],
        },
    )
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        OpenAIDecisionAdapter().evaluate(
            api_key="example-token",
            model="gpt-6-luna",
            state="Example reply.",
            questions={"score": ScoreQuestion(instructions="Rate the reply.", criteria=["Poor", "Good", "Excellent"])},
        )


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (401, "invalid_api_key", AuthenticationError),
        (403, "permission_denied", ModelPermissionError),
        (404, "model_not_found", ModelNotFoundError),
        (408, "request_timeout", ProviderConnectionError),
        (409, "conflict", ProviderConnectionError),
        (429, "insufficient_quota", QuotaExceededError),
        (429, "rate_limit_exceeded", RetryableRateLimitError),
        (500, "internal_error", ProviderConnectionError),
        (503, "unavailable", RetryableRateLimitError),
        (529, "overloaded", RetryableRateLimitError),
        (307, "redirect", ProviderConnectionError),
        (422, "invalid_request", ProviderRequestRejectedError),
    ],
)
def test_http_errors_keep_retryable_and_terminal_failures_distinct(
    status: int, code: str, expected: type[Exception]
) -> None:
    response = _json_response(
        status,
        payload={"error": {"code": code, "message": "Example provider error", "type": code}},
        headers={"retry-after": "12", "Location": "https://redirect.example.com/decisions"},
    )
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response) as transport,
        pytest.raises(expected) as error,
    ):
        OpenAIDecisionAdapter().evaluate(
            api_key="example-token",
            model="gpt-6-luna",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is this a greeting?")},
        )
    assert transport.call_count == 1
    if isinstance(error.value, RetryableRateLimitError):
        assert error.value.retry_after == 12


@pytest.mark.parametrize("error", [httpx.ConnectError("DNS unavailable"), httpx.ReadTimeout("Timed out"), None])
def test_transport_failure_is_retryable(error: httpx.RequestError | None) -> None:
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=error),
        patch("posthog.security.url_validation.resolve_host_ips", return_value=set())
        if error is None
        else nullcontext(),
        pytest.raises(ProviderConnectionError),
    ):
        OpenAIDecisionAdapter().evaluate(
            api_key="example-token",
            model="gpt-6-luna",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is this a greeting?")},
        )


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_total_request_deadline_closes_slow_connections(phase: str) -> None:
    clock = [0.0]
    stream = httpcore.AsyncMockStream([])
    reads = 0

    async def read(max_bytes: int, timeout: float | None = None) -> bytes:
        nonlocal reads
        reads += 1
        clock[0] += 1
        await asyncio.sleep(0)
        if phase == "headers":
            return b"HTTP/1.1 200 OK\r\nX-Slow: " if reads == 1 else b"x"
        return b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" if reads == 1 else b"1\r\nx\r\n"

    response = httpx.Response(
        200,
        json={"model": "gpt-6-luna", "answers": [{"name": "verdict", "type": "predicate", "probability": 0.9}]},
    )
    with (
        patch("asyncio.BaseEventLoop.time", side_effect=lambda: clock[0]),
        patch("httpx.HTTPTransport.handle_request", return_value=response),
        patch("httpcore.AnyIOBackend.connect_tcp", return_value=stream),
        patch.object(stream, "read", side_effect=read),
        patch.object(stream, "aclose", wraps=stream.aclose) as close,
        pytest.raises(ProviderConnectionError),
    ):
        OpenAIDecisionAdapter().evaluate(
            api_key="example-token",
            model="gpt-6-luna",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is this a greeting?")},
        )
    close.assert_awaited()
