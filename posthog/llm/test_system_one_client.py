import json

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
)
from posthog.llm.system_one_client import (
    GatewaySystemOneClient,
    SystemOneClient,
    TypeSafeFallback,
    TypeSafeSystemOneClient,
    build_system_one_client,
)

GATEWAY_MODEL = "posthog/hogference/jevk5-fp8-0.2"
FALLBACK = TypeSafeFallback(model="jev-1.13.0", source="test", priority=Priority.BATCH)
GATEWAY = {"AI_GATEWAY_URL": "https://ai-gateway.example.com/v1", "AI_GATEWAY_API_KEY": "phs_test"}
NOTHING = {"AI_GATEWAY_URL": "", "AI_GATEWAY_API_KEY": "", "TYPESAFE_API_KEY": ""}
QUESTIONS: dict[str, Question] = {
    "urgent": NoulQuestion(instructions="Is this urgent?"),
    "team": ChoiceQuestion(instructions="Which team handles this?", criteria={"billing": None, "support": None}),
}
ANSWERS = {
    "model": GATEWAY_MODEL,
    "answers": {
        # The hogference server leaves out `type`, and TypeSafe sends it.
        "urgent": {"noul": 0.8},
        "team": {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.7,
            "probabilities": {"billing": 0.7, "support": 0.3},
        },
    },
    "usage": {"input_tokens": 42},
}


def _build(typesafe_fallback: TypeSafeFallback | None = FALLBACK) -> SystemOneClient:
    return build_system_one_client(
        model=GATEWAY_MODEL, ai_product="test_product", typesafe_fallback=typesafe_fallback, distinct_id="team-7"
    )


class TestBuildSystemOneClient(SimpleTestCase):
    @parameterized.expand(
        [
            ("gateway_wins", {**GATEWAY, "TYPESAFE_API_KEY": "ts-key"}, GatewaySystemOneClient, GATEWAY_MODEL),
            ("typesafe_fallback", {"TYPESAFE_API_KEY": "ts-key"}, TypeSafeSystemOneClient, FALLBACK.model),
            (
                "gateway_over_plain_http_falls_back",
                {
                    "AI_GATEWAY_URL": "http://ai-gateway.example.com/v1",
                    "AI_GATEWAY_API_KEY": "phs_test",
                    "TYPESAFE_API_KEY": "ts-key",
                },
                TypeSafeSystemOneClient,
                FALLBACK.model,
            ),
        ]
    )
    def test_picks_the_server_and_its_model(
        self, _name: str, configured: dict, kind: type[SystemOneClient], model: str
    ) -> None:
        with override_settings(**{**NOTHING, **configured}):
            client = _build()

        assert isinstance(client, kind)
        assert client.model == model

    @parameterized.expand(
        [
            ("nothing_configured", NOTHING, FALLBACK),
            # A caller that passes no fallback must never reach TypeSafe, even with its key set.
            ("typesafe_not_allowed", {**NOTHING, "TYPESAFE_API_KEY": "ts-key"}, None),
            (
                "gateway_key_over_plain_http",
                {**NOTHING, "AI_GATEWAY_URL": "http://ai-gateway.example.com/v1", "AI_GATEWAY_API_KEY": "phs_test"},
                FALLBACK,
            ),
        ]
    )
    def test_refuses_without_a_usable_server(
        self, _name: str, configured: dict, typesafe_fallback: TypeSafeFallback | None
    ) -> None:
        with override_settings(**configured), self.assertRaises(SystemOneNotConfigured):
            _build(typesafe_fallback)

    def test_gateway_request_reaches_the_system_one_route_with_its_labels(self) -> None:
        with override_settings(**{**NOTHING, **GATEWAY}):
            client = _build()
        with patch.object(httpx.Client, "send", return_value=httpx.Response(200, json=ANSWERS)) as send:
            result = client.decide(state={"ticket": "Payouts fail"}, questions=QUESTIONS)

        request: httpx.Request = send.call_args.args[0]
        assert str(request.url) == "https://ai-gateway.example.com/v1/systemone"
        assert request.headers["Authorization"] == "Bearer phs_test"
        assert request.headers["X-PostHog-Product"] == "test_product"
        assert request.headers["X-PostHog-Distinct-Id"] == "team-7"
        assert json.loads(request.content)["model"] == GATEWAY_MODEL
        assert result.model == GATEWAY_MODEL
        assert result.answers == {
            "urgent": NoulAnswer(probability=0.8),
            "team": ChoiceAnswer(choice="billing", confidence=0.7, probabilities={"billing": 0.7, "support": 0.3}),
        }

    @parameterized.expand(
        [
            ("http_error", httpx.Response(404, json={"error": "not found"}), 404),
            ("unparseable_answer", httpx.Response(200, json={"model": GATEWAY_MODEL, "answers": {}}), None),
            ("unreachable", httpx.ConnectError("refused"), None),
        ]
    )
    def test_gateway_failures_raise_request_failed(self, _name: str, outcome, status_code: int | None) -> None:
        with override_settings(**{**NOTHING, **GATEWAY}):
            client = _build()
        mock = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch.object(httpx.Client, "send", **mock), self.assertRaises(SystemOneRequestFailed) as raised:
            client.decide(state="Payouts fail", questions=QUESTIONS)

        assert raised.exception.status_code == status_code

    @parameterized.expand(
        [
            (
                "choice_past_the_option_limit",
                {
                    "pick": ChoiceQuestion(
                        instructions="Which one?", criteria={f"option_{index}": None for index in range(17)}
                    )
                },
            ),
            (
                "past_the_question_limit",
                {f"question_{index}": NoulQuestion(instructions="Is it?") for index in range(33)},
            ),
        ]
    )
    def test_gateway_rejects_an_oversized_request_before_sending(
        self, _name: str, questions: dict[str, Question]
    ) -> None:
        with override_settings(**{**NOTHING, **GATEWAY}):
            client = _build()

        with patch.object(httpx.Client, "send") as send, self.assertRaises(ValueError):
            client.decide(state="x", questions=questions)

        send.assert_not_called()

    def test_typesafe_fallback_sends_its_model_and_lane(self) -> None:
        with override_settings(**{**NOTHING, "TYPESAFE_API_KEY": "ts-key"}):
            client = _build()
        with patch("posthog.llm.system_one_client.system_one") as system_one:
            client.decide(state="x", questions=QUESTIONS)

        kwargs = system_one.call_args.kwargs
        assert (kwargs["source"], kwargs["model"], kwargs["priority"]) == ("test", FALLBACK.model, Priority.BATCH)
