import pytest
from unittest.mock import Mock, patch

from products.ai_observability.backend.llm.client import Client
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelPermissionError,
    ProviderConnectionError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.llm.typesafe import TypeSafeClient, TypeSafeRateLimitError


@pytest.mark.parametrize("status, expected_state", [(200, "ok"), (401, "invalid"), (403, "invalid"), (500, "error")])
def test_typesafe_key_validation(status: int, expected_state: str) -> None:
    response = Mock(status_code=status)
    response.json.return_value = {"models": [{"name": "jev-latest"}]}
    with patch("requests.request", return_value=response) as request:
        state, message = Client.validate_key("typesafe", "test-typesafe-key")

    assert state == expected_state
    assert (message is None) == (expected_state == "ok")
    assert request.call_args.args == ("GET", "https://api.typesafe.ai/v1/models")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-typesafe-key"


@pytest.mark.parametrize("allows_na", [False, True])
def test_typesafe_boolean_request(allows_na: bool) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": 0.8}, "applicable": {"type": "noul", "noul": 0.2}},
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    with patch("requests.request", return_value=response) as request:
        result = TypeSafeClient.evaluate_boolean(
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
    assert request.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan"), float("inf"), "0.8", True, None])
def test_typesafe_rejects_invalid_probabilities(probability: object) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    with patch("requests.request", return_value=response), pytest.raises(StructuredOutputParseError):
        TypeSafeClient.evaluate_boolean(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            prompt="Is the response polite?",
            source="Hello!",
            allows_na=False,
        )


@pytest.mark.parametrize("status", [429, 529])
def test_typesafe_rate_limits_are_retryable(status: int) -> None:
    response = Mock(status_code=status, headers={"Retry-After": "15"})
    with patch("requests.request", return_value=response), pytest.raises(TypeSafeRateLimitError) as error:
        TypeSafeClient.evaluate_boolean(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            prompt="Is the response polite?",
            source="Hello!",
            allows_na=False,
        )
    assert error.value.retry_after == 15


def test_typesafe_requires_a_key() -> None:
    with patch("requests.request") as request, pytest.raises(AuthenticationError):
        TypeSafeClient.evaluate_boolean(
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
    with patch("requests.request", return_value=response), pytest.raises(StructuredOutputParseError):
        TypeSafeClient.evaluate_boolean(
            api_key="test-typesafe-key", model="jev-1.13.0", prompt="Polite?", source="Hello!", allows_na=True
        )


@pytest.mark.parametrize(
    "status,message,error_type",
    [
        (401, "Invalid key", AuthenticationError),
        (403, "Access denied", ModelPermissionError),
        (500, "Unavailable", ProviderConnectionError),
        (422, "Input exceeds the context window", ContextWindowExceededError),
        (422, "Invalid question", StructuredOutputParseError),
    ],
)
def test_typesafe_preserves_error_categories(status: int, message: str, error_type: type[Exception]) -> None:
    response = Mock(status_code=status, text=message)
    with patch("requests.request", return_value=response), pytest.raises(error_type):
        TypeSafeClient.evaluate_boolean(
            api_key="test-typesafe-key", model="jev-1.13.0", prompt="Polite?", source="Hello!", allows_na=False
        )
