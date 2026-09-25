import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

from products.ai_observability.backend.llm.client import Client
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelPermissionError,
    ProviderConnectionError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.llm.system_one import SystemOneClient, SystemOneRateLimitError


@pytest.mark.parametrize("status, expected_state", [(200, "ok"), (401, "invalid"), (403, "invalid"), (500, "error")])
def test_typesafe_key_validation(status: int, expected_state: str) -> None:
    response = Mock(status_code=status)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": 0.9}, "applicable": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 12, "output_tokens": 0},
    }
    with patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response) as request:
        state, message = Client.validate_key("typesafe", "test-typesafe-key")

    assert state == expected_state
    assert (message is None) == (expected_state == "ok")
    assert request.call_args.args == ("POST", "https://api.typesafe.ai/v1/systemone")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-typesafe-key"


@pytest.mark.parametrize("allows_na", [False, True])
def test_typesafe_boolean_request(allows_na: bool) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": 0.8}, "applicable": {"type": "noul", "noul": 0.2}},
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    with patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response) as request:
        result = SystemOneClient.evaluate_boolean(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            prompt="Is the response polite?",
            source="Hello!",
            allows_na=allows_na,
        )

    assert result.answers["verdict"].noul == 0.8
    body = request.call_args.kwargs["json"]
    assert body["state"] == "Hello!"
    assert body["questions"]["verdict"] == {"type": "noul", "instructions": "Is the response polite?"}
    assert ("applicable" in body["questions"]) == allows_na
    assert request.call_args.args[1] == "https://api.typesafe.ai/v1/systemone"


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan"), float("inf"), "0.8", True, None])
def test_typesafe_rejects_invalid_probabilities(probability: object) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        SystemOneClient.evaluate_boolean(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            prompt="Is the response polite?",
            source="Hello!",
            allows_na=False,
        )


@pytest.mark.parametrize("status", [429, 503, 529])
def test_typesafe_rate_limits_are_retryable(status: int) -> None:
    response = Mock(status_code=status, headers={"Retry-After": "15"})
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(SystemOneRateLimitError) as error,
    ):
        SystemOneClient.evaluate_boolean(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            prompt="Is the response polite?",
            source="Hello!",
            allows_na=False,
        )
    assert error.value.retry_after == 15


def test_typesafe_requires_a_key() -> None:
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request") as request,
        pytest.raises(AuthenticationError),
    ):
        SystemOneClient.evaluate_boolean(
            api_key="", model="jev-1.13.0", prompt="Polite?", source="Hello!", allows_na=False
        )
    request.assert_not_called()


@pytest.mark.parametrize("answers", [{}, {"verdict": {"type": "noul", "noul": 0.9}}])
def test_typesafe_requires_every_requested_answer(answers: dict[str, object]) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 12, "output_tokens": 2},
    }
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        SystemOneClient.evaluate_boolean(
            api_key="test-typesafe-key", model="jev-1.13.0", prompt="Polite?", source="Hello!", allows_na=True
        )


@pytest.mark.parametrize(
    "status,message,error_type",
    [
        (401, "Invalid key", AuthenticationError),
        (403, "Access denied", ModelPermissionError),
        (500, "Unavailable", ProviderConnectionError),
        (413, "Request too large", ContextWindowExceededError),
        (422, "Input exceeds the context window", ContextWindowExceededError),
        (422, "Invalid question", StructuredOutputParseError),
    ],
)
def test_typesafe_preserves_error_categories(status: int, message: str, error_type: type[Exception]) -> None:
    response = Mock(status_code=status, text=message)
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(error_type),
    ):
        SystemOneClient.evaluate_boolean(
            api_key="test-typesafe-key", model="jev-1.13.0", prompt="Polite?", source="Hello!", allows_na=False
        )


@pytest.mark.parametrize("api_key", ["example-token", ""])
def test_custom_endpoint_and_model(api_key: str) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "custom-model-revision",
        "answers": {"verdict": {"type": "noul", "noul": 0.7}, "applicable": {"type": "noul", "noul": 1.0}},
        "usage": {"input_tokens": 15, "output_tokens": 0},
        "latency_ms": 42,
    }
    with patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response) as request:
        result = SystemOneClient.evaluate_boolean(
            api_key=api_key,
            base_url="https://decisions.example.com/v1/",
            model="custom-model",
            prompt="Polite?",
            source="Hello!",
            allows_na=True,
        )
    assert request.call_args.args == ("POST", "https://decisions.example.com/v1/systemone")
    assert request.call_args.kwargs["headers"] == ({"Authorization": f"Bearer {api_key}"} if api_key else {})
    assert request.call_args.kwargs["json"]["model"] == "custom-model"
    assert result.model == "custom-model-revision"
    assert result.usage.output_tokens == 0
    assert result.answers["verdict"].noul == 0.7


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
    with patch("products.ai_observability.backend.llm.system_one.pinned_request") as request:
        state, _ = SystemOneClient.validate_key("example-token", base_url=base_url)
    assert state == "error"
    request.assert_not_called()


def test_private_endpoint_is_blocked() -> None:
    with override_settings(DEBUG=False, TEST=False), patch("requests.Session.request") as request:
        state, _ = SystemOneClient.validate_key("example-token", base_url="https://127.0.0.1/v1")
    assert state == "error"
    request.assert_not_called()
