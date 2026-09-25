import json
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.limiter.policies import Priority, resolve_policy
from posthog.egress.typesafe.client import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    TypeSafeNotConfigured,
    TypeSafeRequestFailed,
    system_one,
)
from posthog.egress.typesafe.limiter import typesafe_account_key

_FAKE_API_KEY = "fake-key-for-tests"

_QUESTIONS: dict[str, Question] = {
    "urgent": NoulQuestion(instructions="Is this urgent?", criteria_true="Time-sensitive"),
    "team": ChoiceQuestion(instructions="Which team handles this?", criteria={"billing": "Payments", "support": None}),
}

_ANSWERS: dict[str, Any] = {
    "model": "jev-1.13.0",
    "answers": {
        "urgent": {"type": "noul", "noul": 0.95},
        "team": {
            "type": "choice",
            "choice": "billing",
            "probabilities": {"billing": 0.88, "support": 0.12},
            "confidence": 0.81,
        },
    },
    "usage": {"input_tokens": 296, "output_tokens": 20},
}

_COUNTER_LABELS = {
    "account": "default",
    "method": "POST",
    "endpoint": "/v1/systemone",
    "status_code": "200",
    "source": "test",
}


def _response(status: int, body: str) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response._content = body.encode()
    return response


def _with_answer(question_id: str, answer: dict[str, Any]) -> str:
    return json.dumps({**_ANSWERS, "answers": {**_ANSWERS["answers"], question_id: answer}})


@override_settings(TYPESAFE_API_KEY=_FAKE_API_KEY)
class TestTypeSafeEgress(SimpleTestCase):
    def test_sends_the_documented_request_and_records_it_without_the_key(self) -> None:
        consume = MagicMock(return_value=True)
        before = REGISTRY.get_sample_value("typesafe_api_requests_total", _COUNTER_LABELS) or 0.0
        with (
            patch("posthog.egress.typesafe.transport.consume_typesafe_sync", consume),
            patch("requests.request", return_value=_response(200, json.dumps(_ANSWERS))) as request,
        ):
            result = system_one(state={"ticket": "Payouts fail"}, questions=_QUESTIONS, source="test")

        assert request.call_args.args == ("POST", "https://api.typesafe.ai/v1/systemone")
        kwargs = request.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == f"Bearer {_FAKE_API_KEY}"
        assert kwargs["json"] == {
            "model": "jev-latest",
            "state": {"ticket": "Payouts fail"},
            "questions": {
                "urgent": {"type": "noul", "instructions": "Is this urgent?", "criteria": {"true": "Time-sensitive"}},
                "team": {
                    "type": "choice",
                    "instructions": "Which team handles this?",
                    "criteria": {"billing": "Payments", "support": None},
                },
            },
        }
        assert result.model == "jev-1.13.0"
        assert result.answers == {
            "urgent": NoulAnswer(probability=0.95),
            "team": ChoiceAnswer(choice="billing", confidence=0.81, probabilities={"billing": 0.88, "support": 0.12}),
        }
        assert result.input_tokens == 296
        assert consume.call_args.kwargs["priority"] is Priority.NORMAL
        assert REGISTRY.get_sample_value("typesafe_api_requests_total", _COUNTER_LABELS) == before + 1
        assert _FAKE_API_KEY not in str(list(REGISTRY.collect()))

    @parameterized.expand(
        [
            ("rate_limited", 429, json.dumps({"error": "rate limited"}), 429),
            ("overloaded", 529, json.dumps({"error": "overloaded"}), 529),
            ("non_json_body", 200, "<html>bad gateway</html>", None),
            (
                "missing_answer",
                200,
                json.dumps({**_ANSWERS, "answers": {"urgent": {"type": "noul", "noul": 0.9}}}),
                None,
            ),
            ("noul_out_of_range", 200, _with_answer("urgent", {"type": "noul", "noul": 1.5}), None),
            ("noul_past_the_float_range", 200, _with_answer("urgent", {"type": "noul", "noul": 10**400}), None),
            (
                "choice_outside_the_options",
                200,
                _with_answer("team", {"type": "choice", "choice": "sales", "probabilities": {}, "confidence": 1.0}),
                None,
            ),
            (
                "choice_missing_an_option_probability",
                200,
                _with_answer(
                    "team",
                    {"type": "choice", "choice": "billing", "probabilities": {"billing": 1.0}, "confidence": 1.0},
                ),
                None,
            ),
            ("missing_model", 200, json.dumps({key: value for key, value in _ANSWERS.items() if key != "model"}), None),
            (
                "answer_of_the_wrong_type",
                200,
                _with_answer("team", {"type": "noul", "noul": 0.5}),
                None,
            ),
        ]
    )
    def test_raises_rather_than_returning_a_partial_answer(
        self, _name: str, status: int, body: str, expected_status_code: int | None
    ) -> None:
        with (
            patch("posthog.egress.typesafe.transport.consume_typesafe_sync", return_value=True),
            patch("requests.request", return_value=_response(status, body)),
            self.assertRaises(TypeSafeRequestFailed) as raised,
        ):
            system_one(state="Payouts fail", questions=_QUESTIONS, source="test")
        assert raised.exception.status_code == expected_status_code

    @parameterized.expand(
        [
            ("no_configured_key", "", Priority.NORMAL, TypeSafeNotConfigured),
            ("critical_lane_skips_the_spend_ceiling", _FAKE_API_KEY, Priority.CRITICAL, ValueError),
        ]
    )
    def test_never_calls_out(self, _name: str, api_key: str, priority: Priority, error: type[Exception]) -> None:
        with (
            override_settings(TYPESAFE_API_KEY=api_key),
            patch("requests.request") as request,
            self.assertRaises(error),
        ):
            system_one(state="hi", questions=_QUESTIONS, source="test", priority=priority)
        request.assert_not_called()

    @override_settings(TYPESAFE_EGRESS_PER_MINUTE_BUDGET=7, TYPESAFE_EGRESS_HOURLY_BUDGET=11)
    def test_budgets_come_from_the_settings_they_are_named_after(self) -> None:
        assert resolve_policy(typesafe_account_key()).limits == ((7, 60.0), (11, 3600.0))
