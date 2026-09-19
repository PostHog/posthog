import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.egress.typesafe.client import (
    JEV_MODEL,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    TypesafeCallFailed,
    TypesafeNotConfigured,
    system_one,
)

_FAKE_API_KEY = "fake-key-for-tests"

_QUESTIONS = {
    "pick": ChoiceQuestion(instructions="Pick one.", criteria={"a": "Option a", "b": "Option b"}),
    "holds": NoulQuestion(instructions="Does it hold?", true="It holds.", false="It does not."),
}


def _response(status: int, body: object) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    return response


def _answers(choice: str = "a") -> dict[str, object]:
    return {
        "model": JEV_MODEL,
        "answers": {
            "pick": {"type": "choice", "choice": choice, "confidence": 0.8, "probabilities": {"a": 0.8, "b": 0.2}},
            "holds": {"type": "noul", "noul": 0.35},
        },
        "usage": {"input_tokens": 120, "output_tokens": 0},
    }


@override_settings(TYPESAFE_API_KEY=_FAKE_API_KEY)
class TestTypesafeEgress(SimpleTestCase):
    def test_sends_the_request_shape_typesafe_documents(self) -> None:
        with (
            patch("posthog.egress.typesafe.transport.consume_typesafe_sync", MagicMock(return_value=True)),
            patch("requests.request", return_value=_response(200, _answers())) as request,
        ):
            result = system_one(state={"subject": {"name": "x"}}, questions=_QUESTIONS, source="test")

        assert request.call_args.args == ("POST", "https://api.typesafe.ai/v1/systemone")
        assert request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {_FAKE_API_KEY}"
        assert request.call_args.kwargs["json"] == {
            "model": JEV_MODEL,
            "state": {"subject": {"name": "x"}},
            "questions": {
                "pick": {"type": "choice", "instructions": "Pick one.", "criteria": {"a": "Option a", "b": "Option b"}},
                "holds": {
                    "type": "noul",
                    "instructions": "Does it hold?",
                    "criteria": {"true": "It holds.", "false": "It does not."},
                },
            },
        }
        assert result.answers["pick"] == ChoiceAnswer(choice="a", confidence=0.8, probabilities={"a": 0.8, "b": 0.2})
        assert result.answers["holds"] == NoulAnswer(probability=0.35)
        assert result.input_tokens == 120

    @parameterized.expand(
        [
            ("unknown_option", 200, _answers(choice="zzz")),
            ("missing_answer", 200, {"answers": {"pick": {"type": "choice", "choice": "a", "confidence": 0.5}}}),
            (
                "wrong_type",
                200,
                {"answers": {"pick": {"type": "noul", "noul": 0.9}, "holds": {"type": "noul", "noul": 0.1}}},
            ),
            ("http_error", 429, {"error": "slow down"}),
            ("no_answers", 200, {"model": JEV_MODEL}),
        ]
    )
    def test_rejects_responses_outside_the_documented_shape(self, _name: str, status: int, body: object) -> None:
        with (
            patch("posthog.egress.typesafe.transport.consume_typesafe_sync", MagicMock(return_value=True)),
            patch("requests.request", return_value=_response(status, body)),
        ):
            with self.assertRaises(TypesafeCallFailed):
                system_one(state={}, questions=_QUESTIONS, source="test")

    @override_settings(TYPESAFE_API_KEY="")
    def test_makes_no_request_without_an_api_key(self) -> None:
        with patch("requests.request") as request:
            with self.assertRaises(TypesafeNotConfigured):
                system_one(state={}, questions=_QUESTIONS, source="test")
        request.assert_not_called()

    def test_choice_question_rejects_more_options_than_typesafe_accepts(self) -> None:
        with self.assertRaises(ValueError):
            ChoiceQuestion(instructions="Pick.", criteria={f"o{i}": "x" for i in range(256)})
