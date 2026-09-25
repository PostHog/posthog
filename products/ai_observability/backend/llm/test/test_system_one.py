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
from products.ai_observability.backend.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneClient,
    SystemOneQuestion,
    SystemOneRateLimitError,
    SystemOneRequestRejectedError,
)


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


def test_typesafe_mixed_question_request() -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {
            "verdict": {"type": "noul", "noul": 0.8},
            "quality": {
                "type": "score",
                "score": 1.25,
                "legend": {"0": "Poor", "1": "Fair", "2": "Good"},
                "probabilities": {"0": 0.1, "1": 0.55, "2": 0.35},
                "confidence": 0.6,
            },
            "language": {"type": "choice", "choice": "en", "probabilities": {"en": 0.7, "es": 0.3}, "confidence": 0.4},
        },
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    with patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response) as request:
        result = SystemOneClient.evaluate(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            state={"text": "Hello!"},
            questions={
                "verdict": NoulQuestion(instructions="Is the response polite?"),
                "quality": ScoreQuestion(instructions="Assess quality", criteria=["Poor", "Fair", "Good"]),
                "language": ChoiceQuestion(
                    instructions={"question": "Which language?"}, criteria={"en": None, "es": None}
                ),
            },
        )

    assert isinstance(result.answers["verdict"], NoulAnswer)
    assert result.answers["verdict"].noul == 0.8
    assert isinstance(result.answers["quality"], ScoreAnswer)
    assert result.answers["quality"].score == 1.25
    assert isinstance(result.answers["language"], ChoiceAnswer)
    assert result.answers["language"].choice == "en"
    body = request.call_args.kwargs["json"]
    assert body["state"] == {"text": "Hello!"}
    assert body["questions"]["verdict"] == {"type": "noul", "instructions": "Is the response polite?"}
    assert body["questions"]["quality"] == {
        "type": "score",
        "instructions": "Assess quality",
        "criteria": ["Poor", "Fair", "Good"],
    }
    assert body["questions"]["language"] == {
        "type": "choice",
        "instructions": {"question": "Which language?"},
        "criteria": {"en": None, "es": None},
    }
    assert request.call_args.args[1] == "https://api.typesafe.ai/v1/systemone"


@pytest.mark.parametrize(
    "question,answer",
    [
        (ScoreQuestion(criteria=["Poor", "Good"]), {"type": "noul", "noul": 0.8}),
        *[
            (
                ScoreQuestion(criteria=["Poor", "Good"]),
                {
                    "type": "score",
                    "score": 0.75,
                    "confidence": 0.5,
                    "legend": {"0": "Poor", "1": "Good"},
                    "probabilities": {"0": 0.25, "1": 0.75},
                    field: value,
                },
            )
            for field, value in [
                ("score", 1.1),
                ("score", True),
                ("score", float("nan")),
                ("legend", {"0": "Poor"}),
                ("probabilities", {"0": 0.25, "2": 0.75}),
                ("probabilities", {"0": 0.25, "1": 0.25}),
            ]
        ],
        (
            ChoiceQuestion(criteria={"en": None, "es": None}),
            {"type": "choice", "choice": "fr", "confidence": 0.5, "probabilities": {"en": 0.25, "es": 0.75}},
        ),
    ],
)
def test_rejects_answers_that_do_not_match_the_requested_scale(
    question: SystemOneQuestion, answer: dict[str, object]
) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "custom-model",
        "answers": {"result": answer},
        "usage": {"input_tokens": 12, "output_tokens": 2},
    }
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(StructuredOutputParseError),
    ):
        SystemOneClient.evaluate(
            api_key="example-token", model="custom-model", state="Hello!", questions={"result": question}
        )


def test_choice_accepts_a_rounded_distribution_with_many_options() -> None:
    criteria = {str(index): None for index in range(255)}
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "custom-model",
        "answers": {
            "result": {
                "type": "choice",
                "choice": "0",
                "confidence": 0,
                "probabilities": dict.fromkeys(criteria, 0.0039),
            }
        },
        "usage": {"input_tokens": 12, "output_tokens": 0},
    }
    with patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response):
        result = SystemOneClient.evaluate(
            api_key="",
            base_url="https://decisions.example.com/v1",
            model="custom-model",
            state="Hello!",
            questions={"result": ChoiceQuestion(criteria=criteria)},
        )
    assert isinstance(result.answers["result"], ChoiceAnswer)
    assert result.answers["result"].choice == "0"


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
        SystemOneClient.evaluate(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is the response polite?")},
        )


@pytest.mark.parametrize("status", [429, 503, 529])
def test_typesafe_rate_limits_are_retryable(status: int) -> None:
    response = Mock(status_code=status, headers={"Retry-After": "15"})
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(SystemOneRateLimitError) as error,
    ):
        SystemOneClient.evaluate(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is the response polite?")},
        )
    assert error.value.retry_after == 15


def test_typesafe_requires_a_key() -> None:
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request") as request,
        pytest.raises(AuthenticationError),
    ):
        SystemOneClient.evaluate(
            api_key="", model="jev-1.13.0", state="Hello!", questions={"verdict": NoulQuestion(instructions="Polite?")}
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
        SystemOneClient.evaluate(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            state="Hello!",
            questions={
                "verdict": NoulQuestion(instructions="Polite?"),
                "applicable": NoulQuestion(instructions="Relevant?"),
            },
        )


@pytest.mark.parametrize(
    "status,message,error_type",
    [
        (401, "Invalid key", AuthenticationError),
        (403, "Access denied", ModelPermissionError),
        (500, "Unavailable", ProviderConnectionError),
        (413, "Request too large", ContextWindowExceededError),
        (422, "Input exceeds the context window", ContextWindowExceededError),
        (422, "Invalid question", SystemOneRequestRejectedError),
    ],
)
def test_typesafe_preserves_error_categories(status: int, message: str, error_type: type[Exception]) -> None:
    response = Mock(status_code=status, text=message)
    with (
        patch("products.ai_observability.backend.llm.system_one.pinned_request", return_value=response),
        pytest.raises(error_type),
    ):
        SystemOneClient.evaluate(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Polite?")},
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
        result = SystemOneClient.evaluate(
            api_key=api_key,
            base_url="https://decisions.example.com/v1/",
            model="custom-model",
            state="Hello!",
            questions={
                "verdict": NoulQuestion(instructions="Polite?"),
                "applicable": NoulQuestion(instructions="Relevant?"),
            },
        )
    assert request.call_args.args == ("POST", "https://decisions.example.com/v1/systemone")
    assert request.call_args.kwargs["headers"] == ({"Authorization": f"Bearer {api_key}"} if api_key else {})
    assert request.call_args.kwargs["json"]["model"] == "custom-model"
    assert result.model == "custom-model-revision"
    assert result.usage.output_tokens == 0
    assert isinstance(result.answers["verdict"], NoulAnswer)
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
