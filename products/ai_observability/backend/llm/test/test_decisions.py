import json
from collections.abc import Iterator
from contextlib import nullcontext
from ipaddress import ip_address
from typing import Literal
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.test import override_settings

import httpx

from posthog.llm.system_one import NoulAnswer, NoulQuestion, ScoreAnswer, ScoreQuestion
from posthog.models import Team

from products.ai_observability.backend.llm.client import Client
from products.ai_observability.backend.llm.decisions import (
    DecisionClient,
    DecisionEndpointBlockedError,
    DecisionRateLimitError,
    DecisionRequestRejectedError,
    decision_evaluations_enabled,
)
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelPermissionError,
    ProviderConnectionError,
    ProviderHostUnresolvedError,
    QuotaExceededError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.llm.providers.openrouter import OPENROUTER_DECISIONS_BASE_URL, OPENROUTER_HEADERS


def _response(status: int, body: dict[str, object] | str = "") -> httpx.Response:
    return httpx.Response(
        status, stream=httpx.ByteStream((json.dumps(body) if isinstance(body, dict) else body).encode())
    )


@pytest.fixture(autouse=True)
def public_endpoint_dns() -> Iterator[None]:
    with (
        patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("8.8.8.8")}),
    ):
        yield


@pytest.mark.parametrize(
    "base_url,flag,enabled",
    [
        ("https://api.typesafe.ai/v1", True, False),
        ("", True, False),
        ("https://decisions.example.com/v1", True, True),
        ("https://decisions.example.com/v1", False, False),
        ("https://decisions.example.com/v1", None, False),
        ("https://ai-gateway.us.posthog.com/v1", True, True),
        ("https://ai-gateway.eu.posthog.com/v1", True, True),
        ("https://AI-GATEWAY.US.POSTHOG.COM.:443/v1", True, True),
        ("https://ａｉ-gateway.us.posthog.com/v1", True, True),
        ("https://ai-gateway.us.posthog.com/v1", False, False),
        ("https://ai-gateway.us.posthog.com/v1", None, False),
    ],
)
def test_system_one_connections_require_flag_and_supported_endpoint(
    base_url: str, flag: bool | None, enabled: bool
) -> None:
    team = Team(id=1, organization_id=uuid4(), uuid=uuid4())
    with (
        override_settings(POSTHOG_INTERNAL_ORG_IDS=[]),
        patch("products.ai_observability.backend.llm.decisions.Team.objects.only") as teams,
        patch(
            "products.ai_observability.backend.llm.decisions.get_feature_flag_or_none",
            side_effect=lambda *args, groups, **kwargs: flag if groups["project"] == str(team.uuid) else False,
        ),
    ):
        teams.return_value.get.return_value = team
        assert decision_evaluations_enabled(team.id, base_url=base_url) is enabled


@pytest.mark.parametrize(
    "status, expected_state", [(200, "ok"), (401, "invalid"), (402, "error"), (403, "invalid"), (500, "error")]
)
def test_system_one_key_validation(status: int, expected_state: str) -> None:
    response = _response(
        status,
        {
            "model": "example-judge-v1",
            "answers": {"verdict": {"type": "noul", "noul": 0.9}, "applicable": {"type": "noul", "noul": 0.9}},
            "usage": {"input_tokens": 12, "output_tokens": 0},
        },
    )
    response.headers["x-request-id"] = "example-request-id"
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response) as request,
        patch("posthoganalytics.tag") as tag,
    ):
        state, message = Client.validate_key(
            "system_one", "example-token", base_url="https://decisions.example.com/v1", model="custom-model"
        )

    assert state == expected_state
    tag.assert_any_call("provider.last_status", status)
    tag.assert_any_call("provider.last_request_id", "example-request-id")
    assert (message is None) == (expected_state == "ok")
    assert str(request.call_args.args[0].url) == "https://decisions.example.com/v1/systemone"
    assert request.call_args.args[0].headers["Authorization"] == "Bearer example-token"
    assert request.call_args.args[0].extensions["timeout"] == {"connect": 10, "read": 10, "write": 10, "pool": 10}


@pytest.mark.parametrize(
    "error,expected_error",
    [
        (httpx.ConnectError("Connection refused"), ProviderConnectionError),
        (httpx.ReadTimeout("Timed out"), ProviderConnectionError),
        (httpx.DecodingError("The endpoint must return an uncompressed response."), DecisionRequestRejectedError),
        (httpx.DecodingError("The endpoint response exceeds the size limit."), DecisionRequestRejectedError),
    ],
)
def test_transport_failures_map_to_provider_errors(error: Exception, expected_error: type[Exception]) -> None:
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=error),
        pytest.raises(expected_error),
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url="https://decisions.example.com/v1",
            model="custom-model",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is this a greeting?")},
        )


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan"), float("inf"), "0.8", True, None])
def test_system_one_rejects_invalid_probabilities(probability: object) -> None:
    response = _response(
        200,
        {
            "model": "example-judge-v1",
            "answers": {"verdict": {"type": "noul", "noul": probability}},
            "usage": {"input_tokens": 120, "output_tokens": 10},
        },
    )
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url="https://decisions.example.com/v1",
            model="example-judge-v1",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is the response polite?")},
        )


@pytest.mark.parametrize(
    "patch_answer,valid",
    [
        ({}, True),
        ({"score": 0}, True),
        ({"score": 2}, True),
        ({"score": -0.1}, False),
        ({"score": 2.1}, False),
        ({"score": True}, False),
        ({"score": "1.5"}, False),
        ({"score": float("nan")}, False),
        ({"score": float("inf")}, False),
        ({"type": "choice"}, False),
        ({"confidence": 1.1}, False),
        ({"probabilities": {"0": 0.5, "1": 0.5}}, False),
        ({"probabilities": {"0": 0, "1": 0, "2": True}}, False),
    ],
)
def test_system_one_score_response(patch_answer: dict[str, object], valid: bool) -> None:
    answer = {"score": 1.5, "confidence": 0.5, "probabilities": {"0": 0.0, "1": 0.5, "2": 0.5}, **patch_answer}
    question = ScoreQuestion(instructions="Rate answer quality.", criteria=["Incorrect", "Partly correct", "Correct"])
    with (
        patch(
            "httpx.AsyncHTTPTransport.handle_async_request",
            return_value=_response(200, {"model": "custom-model", "answers": {"score": answer}}),
        ) as request,
        nullcontext() if valid else pytest.raises(StructuredOutputParseError),
    ):
        result = DecisionClient.evaluate(
            api_key="",
            base_url="https://decisions.example.com/v1",
            model="custom-model",
            state="Hello!",
            questions={"score": question},
        )
    if not valid:
        return
    parsed = result.answers["score"]
    assert isinstance(parsed, ScoreAnswer)
    assert parsed.score == answer["score"]
    assert parsed.confidence == 0.5
    assert parsed.probabilities == {"0": 0.0, "1": 0.5, "2": 0.5}
    assert json.loads(request.call_args.args[0].content)["questions"]["score"] == {
        "type": "score",
        "instructions": "Rate answer quality.",
        "criteria": ["Incorrect", "Partly correct", "Correct"],
    }


@pytest.mark.parametrize("level_count", [0, 1, 11])
def test_system_one_rejects_unsupported_score_rubric_sizes(level_count: int) -> None:
    with pytest.raises(ValueError, match="between 2 and 10"):
        ScoreQuestion(instructions="Score quality.", criteria=[str(index) for index in range(level_count)])


@pytest.mark.parametrize("status", [408, 429, 503, 529])
def test_system_one_rate_limits_are_retryable(status: int) -> None:
    response = _response(status)
    response.headers["Retry-After"] = "15"
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        pytest.raises(DecisionRateLimitError) as error,
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url="https://decisions.example.com/v1",
            model="example-judge-v1",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is the response polite?")},
        )
    assert error.value.retry_after == 15


@pytest.mark.parametrize(
    "usage,expected_input,expected_output",
    [
        ({}, None, None),
        ({"input_tokens": -1, "output_tokens": 0}, None, 0),
        ({"input_tokens": 1, "output_tokens": True}, 1, None),
    ],
)
def test_unavailable_usage_does_not_discard_a_valid_answer(
    usage: dict[str, object], expected_input: int | None, expected_output: int | None
) -> None:
    response = _response(
        200,
        {
            "model": "example-judge-v1",
            "answers": {"verdict": {"type": "noul", "noul": 0.9}},
            "usage": usage,
        },
    )
    with patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response):
        result = DecisionClient.evaluate(
            api_key="example-token",
            base_url="https://decisions.example.com/v1",
            model="example-judge-v1",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Polite?")},
        )

    assert result.input_tokens == expected_input
    assert result.output_tokens == expected_output


@pytest.mark.parametrize(
    "base_url",
    ["https://api.typesafe.ai/v1", "https://API.TYPESAFE.AI.:443/v1", "https://ａｐｉ.typesafe.ai/v1"],
)
def test_official_endpoint_is_blocked(base_url: str) -> None:
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request") as request,
        pytest.raises(DecisionEndpointBlockedError, match="hosted endpoint is not available"),
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url=base_url,
            model="example-judge-v1",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Polite?")},
        )
    request.assert_not_called()


@pytest.mark.parametrize("answers", [{}, {"verdict": {"type": "noul", "noul": 0.9}}])
def test_system_one_requires_every_requested_answer(answers: dict[str, object]) -> None:
    response = _response(
        200,
        {
            "model": "example-judge-v1",
            "answers": answers,
            "usage": {"input_tokens": 12, "output_tokens": 2},
        },
    )
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url="https://decisions.example.com/v1",
            model="example-judge-v1",
            state="Hello!",
            questions={
                "verdict": NoulQuestion(instructions="Polite?"),
                "applicable": NoulQuestion(instructions="Relevant?"),
            },
        )


@pytest.mark.parametrize(
    "status,message,error_type,path",
    [
        (200, "<html>Bad gateway</html>", StructuredOutputParseError, "systemone"),
        (302, "Redirect", DecisionEndpointBlockedError, "systemone"),
        (302, "Redirect", ProviderConnectionError, "decisions"),
        (401, "Invalid key", AuthenticationError, "systemone"),
        (402, "Insufficient credits", QuotaExceededError, "systemone"),
        (403, "Access denied", ModelPermissionError, "systemone"),
        (500, "Unavailable", ProviderConnectionError, "systemone"),
        (413, "Request too large", ContextWindowExceededError, "systemone"),
        (422, "Input exceeds the context window", ContextWindowExceededError, "systemone"),
        (422, "Invalid question", DecisionRequestRejectedError, "systemone"),
    ],
)
def test_decision_requests_preserve_error_categories(
    status: int, message: str, error_type: type[Exception], path: Literal["systemone", "decisions"]
) -> None:
    response = _response(status, message)
    response.headers["Location"] = "https://other.example.com/systemone"
    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", return_value=response) as request,
        pytest.raises(error_type),
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url=OPENROUTER_DECISIONS_BASE_URL if path == "decisions" else "https://decisions.example.com/v1",
            path=path,
            model="example-judge-v1",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Polite?")},
        )
    request.assert_called_once()


@pytest.mark.parametrize(
    "path,address,error_type",
    [
        ("decisions", None, ProviderHostUnresolvedError),
        ("systemone", None, ProviderHostUnresolvedError),
        ("decisions", "127.0.0.1", DecisionEndpointBlockedError),
        ("systemone", "127.0.0.1", DecisionEndpointBlockedError),
    ],
)
def test_endpoint_resolution_errors(
    path: Literal["systemone", "decisions"], address: str | None, error_type: type[Exception]
) -> None:
    with (
        override_settings(DEBUG=False, TEST=False),
        patch(
            "posthog.security.url_validation.resolve_host_ips", return_value={ip_address(address)} if address else set()
        ),
        patch("httpx.AsyncHTTPTransport.handle_async_request") as request,
        pytest.raises(error_type),
    ):
        DecisionClient.evaluate(
            api_key="example-token",
            base_url=OPENROUTER_DECISIONS_BASE_URL if path == "decisions" else "https://decisions.example.com/v1",
            path=path,
            model="example-judge-v1",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Polite?")},
        )
    request.assert_not_called()


@override_settings(
    DEBUG=False,
    TEST=False,
    AI_GATEWAY_URL="https://gateway.example.com/v1",
    AI_GATEWAY_API_KEY="example-gateway-key",
    TYPESAFE_API_KEY="example-instance-key",
)
@pytest.mark.parametrize("api_key", ["example-token", ""])
@pytest.mark.parametrize("path", ["systemone", "decisions"])
def test_custom_endpoint_and_model(api_key: str, path: Literal["systemone", "decisions"]) -> None:
    base_url = OPENROUTER_DECISIONS_BASE_URL if path == "decisions" else "https://decisions.example.com/v1"
    host = "openrouter.ai" if path == "decisions" else "decisions.example.com"
    response = _response(
        200,
        {
            "model": "custom-model-revision",
            "answers": {"verdict": {"noul": 0.7}, "applicable": {"noul": 1.0}},
            "usage": {"input_tokens": 15},
            "latency_ms": 42,
        },
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "8.8.8.8"
        assert request.headers["Host"] == host
        assert request.extensions["sni_hostname"] == host
        return response

    with (
        patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=respond) as request,
        patch("posthog.egress.typesafe.transport.consume_typesafe_sync") as budget,
        patch("posthog.egress.typesafe.observability.typesafe_egress.record_response") as telemetry,
    ):
        result = DecisionClient.evaluate(
            api_key=api_key,
            base_url=f"{base_url}/",
            path=path,
            model="custom-model",
            state="Hello!",
            questions={
                "verdict": NoulQuestion(instructions="Polite?"),
                "applicable": NoulQuestion(instructions="Relevant?"),
            },
        )
    assert str(request.call_args.args[0].url) == f"{base_url}/{path}"
    assert request.call_args.args[0].headers.get("Authorization") == (f"Bearer {api_key}" if api_key else None)
    for name, value in OPENROUTER_HEADERS.items():
        assert request.call_args.args[0].headers.get(name) == (value if path == "decisions" else None)
    assert json.loads(request.call_args.args[0].content)["model"] == "custom-model"
    budget.assert_not_called()
    telemetry.assert_not_called()
    assert result.model == "custom-model-revision"
    assert result.input_tokens == 15
    assert result.output_tokens is None
    assert isinstance(result.answers["verdict"], NoulAnswer)
    assert result.answers["verdict"].probability == 0.7


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/v1?token=secret",
        "https://example.com/v1#fragment",
    ],
)
def test_invalid_endpoint_is_rejected_before_sending_credentials(base_url: str) -> None:
    with patch("httpx.AsyncHTTPTransport.handle_async_request") as request:
        state, _ = DecisionClient.validate_key("example-token", base_url=base_url, model="custom-model")
    assert state == "error"
    request.assert_not_called()


@pytest.mark.parametrize("base_url", ["https://127.0.0.1/v1", "https://decisions.example.com/v1"])
def test_private_endpoint_is_blocked(base_url: str) -> None:
    with (
        override_settings(DEBUG=False, TEST=False),
        patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("127.0.0.1")}),
        patch("httpx.AsyncHTTPTransport.handle_async_request") as request,
    ):
        state, _ = DecisionClient.validate_key("example-token", base_url=base_url, model="custom-model")
    assert state == "error"
    request.assert_not_called()
