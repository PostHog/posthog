from collections.abc import Iterator
from ipaddress import ip_address
from uuid import uuid4

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

from posthog.egress.typesafe.client import NoulAnswer, NoulQuestion
from posthog.models import Team

from products.ai_observability.backend.llm.client import Client
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelPermissionError,
    ProviderConnectionError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.llm.system_one import (
    SystemOneClient,
    SystemOneRateLimitError,
    SystemOneRequestRejectedError,
    system_one_evaluations_enabled,
)


@pytest.fixture(autouse=True)
def isolated_egress_budget() -> Iterator[None]:
    with (
        patch("posthog.egress.limiter.backends.LimitsBackend.consume_sync", return_value=True),
        patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("8.8.8.8")}),
    ):
        yield


@pytest.mark.parametrize(
    "internal,flag,enabled", [(False, True, False), (True, False, False), (True, None, False), (True, True, True)]
)
def test_system_one_experiment_requires_internal_project_and_flag(
    internal: bool, flag: bool | None, enabled: bool
) -> None:
    team = Team(id=1, organization_id=uuid4(), uuid=uuid4())
    with (
        override_settings(POSTHOG_INTERNAL_ORG_IDS=[str(team.organization_id)] if internal else []),
        patch("products.ai_observability.backend.llm.system_one.Team.objects.only") as teams,
        patch("products.ai_observability.backend.llm.system_one.get_feature_flag_or_none", return_value=flag),
    ):
        teams.return_value.get.return_value = team
        assert system_one_evaluations_enabled(team.id) is enabled


@pytest.mark.parametrize("status, expected_state", [(200, "ok"), (401, "invalid"), (403, "invalid"), (500, "error")])
def test_typesafe_key_validation(status: int, expected_state: str) -> None:
    response = Mock(status_code=status)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": 0.9}, "applicable": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 12, "output_tokens": 0},
    }
    with patch("requests.Session.request", return_value=response) as request:
        state, message = Client.validate_key("typesafe", "test-typesafe-key")

    assert state == expected_state
    assert (message is None) == (expected_state == "ok")
    assert request.call_args.args == ("POST", "https://api.typesafe.ai/v1/systemone")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-typesafe-key"


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan"), float("inf"), "0.8", True, None])
def test_typesafe_rejects_invalid_probabilities(probability: object) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    with (
        patch("requests.Session.request", return_value=response),
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
        patch("requests.Session.request", return_value=response),
        pytest.raises(SystemOneRateLimitError) as error,
    ):
        SystemOneClient.evaluate(
            api_key="test-typesafe-key",
            model="jev-1.13.0",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Is the response polite?")},
        )
    assert error.value.retry_after == 15


@pytest.mark.parametrize(
    "usage", [{}, {"input_tokens": -1, "output_tokens": 0}, {"input_tokens": 1, "output_tokens": True}]
)
def test_invalid_usage_does_not_become_a_billable_evaluation(usage: dict[str, object]) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {"verdict": {"type": "noul", "noul": 0.9}},
        "usage": usage,
    }
    with patch("requests.Session.request", return_value=response), pytest.raises(StructuredOutputParseError):
        SystemOneClient.evaluate(
            api_key="example-token",
            model="jev-1.13.0",
            state="Hello!",
            questions={"verdict": NoulQuestion(instructions="Polite?")},
        )


def test_typesafe_requires_a_key() -> None:
    with (
        patch("requests.Session.request") as request,
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
        patch("requests.Session.request", return_value=response),
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
        patch("requests.Session.request", return_value=response),
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
    with patch("requests.Session.request", return_value=response) as request:
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
    assert request.call_args.kwargs["headers"].get("Authorization") == (f"Bearer {api_key}" if api_key else None)
    assert request.call_args.kwargs["allow_redirects"] is False
    assert request.call_args.kwargs["json"]["model"] == "custom-model"
    assert result.model == "custom-model-revision"
    assert result.output_tokens == 0
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
    with patch("requests.Session.request") as request:
        state, _ = SystemOneClient.validate_key("example-token", base_url=base_url)
    assert state == "error"
    request.assert_not_called()


def test_private_endpoint_is_blocked() -> None:
    with (
        override_settings(DEBUG=False, TEST=False),
        patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("127.0.0.1")}),
        patch("requests.Session.request") as request,
    ):
        state, _ = SystemOneClient.validate_key("example-token", base_url="https://127.0.0.1/v1")
    assert state == "error"
    request.assert_not_called()
