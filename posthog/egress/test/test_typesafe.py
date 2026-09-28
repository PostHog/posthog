import json
import time
from collections.abc import AsyncIterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from threading import Thread
from typing import Any

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.limiter.policies import Priority, resolve_policy
from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.typesafe.client import MAX_RESPONSE_BYTES, TypeSafeNotConfigured, TypeSafeRequestFailed, system_one
from posthog.egress.typesafe.limiter import typesafe_account_key
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, NoulAnswer, NoulQuestion, Question

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


class _ResponseContent:
    def __init__(self, body: str) -> None:
        self.body = body.encode()
        self.read_count = 0

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for offset in range(0, len(self.body), size):
            self.read_count += 1
            yield self.body[offset : offset + size]


class _Response:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self.content = _ResponseContent(body)

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


def _response(status: int, body: str) -> _Response:
    return _Response(status, body)


def _with_answer(question_id: str, answer: dict[str, Any]) -> str:
    return json.dumps({**_ANSWERS, "answers": {**_ANSWERS["answers"], question_id: answer}})


@override_settings(TYPESAFE_API_KEY=_FAKE_API_KEY)
class TestTypeSafeEgress(SimpleTestCase):
    @parameterized.expand(
        [
            ("instance_key", None, "https://api.typesafe.ai/v1"),
            ("explicit_instance_key", _FAKE_API_KEY, "https://api.typesafe.ai/v1"),
            ("customer_key", "fake-customer-key", "https://api.typesafe.ai/v1"),
            ("custom_endpoint", "fake-customer-key", "https://decisions.example.com/v1"),
            ("custom_no_auth", "", "https://decisions.example.com/v1"),
        ]
    )
    def test_sends_the_documented_request_and_records_it_without_the_key(
        self, _name: str, api_key: str | None, base_url: str
    ) -> None:
        resolved_key = _FAKE_API_KEY if api_key is None else api_key
        scope = (
            "default"
            if base_url == "https://api.typesafe.ai/v1" and resolved_key == _FAKE_API_KEY
            else scope_fingerprint(base_url, resolved_key)
        )
        labels = {**_COUNTER_LABELS, "account": scope}
        before = REGISTRY.get_sample_value("typesafe_api_requests_total", labels) or 0.0
        with (
            patch("posthog.egress.limiter.backends.LimitsBackend.consume_sync", return_value=True) as consume,
            patch(
                "aiohttp.ClientSession.request",
                new_callable=AsyncMock,
                return_value=_response(200, json.dumps(_ANSWERS)),
            ) as request,
        ):
            result = system_one(
                state={"ticket": "Payouts fail"},
                questions=_QUESTIONS,
                source="test",
                api_key=api_key,
                base_url=base_url,
            )

        assert request.call_args.args == ("POST", f"{base_url}/systemone")
        kwargs = request.call_args.kwargs
        assert kwargs["headers"].get("Authorization") == (f"Bearer {resolved_key}" if resolved_key else None)
        assert kwargs["headers"]["Accept-Encoding"] == "identity"
        assert kwargs["allow_redirects"] is False
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
        assert result.output_tokens == 20
        assert consume.call_args.args[0] == typesafe_account_key(scope)
        assert consume.call_args.args[3] is Priority.NORMAL
        assert REGISTRY.get_sample_value("typesafe_api_requests_total", labels) == before + 1
        metrics = str(list(REGISTRY.collect()))
        assert _FAKE_API_KEY not in metrics
        assert "fake-customer-key" not in metrics
        assert "decisions.example.com" not in metrics

    @parameterized.expand(
        [
            ("rate_limited", 429, json.dumps({"error": "rate limited"}), 429),
            ("overloaded", 529, json.dumps({"error": "overloaded"}), 529),
            ("redirect", 302, "", 302),
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
            patch("aiohttp.ClientSession.request", new_callable=AsyncMock, return_value=_response(status, body)),
            self.assertRaises(TypeSafeRequestFailed) as raised,
        ):
            system_one(state="Payouts fail", questions=_QUESTIONS, source="test")
        assert raised.exception.status_code == expected_status_code

    @parameterized.expand(
        [
            ("declared", "{}", {"Content-Length": str(MAX_RESPONSE_BYTES + 1)}),
            ("streamed", "x" * (MAX_RESPONSE_BYTES + 1), {}),
            ("compressed", json.dumps(_ANSWERS), {"Content-Encoding": "gzip"}),
        ]
    )
    def test_rejects_endpoint_responses_over_its_limits(self, _name: str, body: str, headers: dict[str, str]) -> None:
        response = _response(200, body)
        response.headers.update(headers)
        with (
            patch("posthog.egress.typesafe.transport.consume_typesafe_sync", return_value=True),
            patch("aiohttp.ClientSession.request", new_callable=AsyncMock, return_value=response),
            self.assertRaisesRegex(TypeSafeRequestFailed, "exceeded its limits"),
        ):
            system_one(state="hello", questions=_QUESTIONS, source="test")

    @parameterized.expand(["headers", "body"])
    def test_slow_response_cannot_extend_the_total_time_limit(self, slow_part: str) -> None:
        class SlowResponse(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.connection.sendall(b"HTTP/1.1 200 OK\r\n")
                self.connection.sendall(b"X-Slow: " if slow_part == "headers" else b"Content-Length: 20\r\n\r\n")
                for _ in range(20):
                    time.sleep(0.1)
                    try:
                        self.connection.sendall(b"x")
                    except OSError:
                        return

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowResponse)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            started_at = time.monotonic()
            with (
                patch("posthog.egress.typesafe.transport.consume_typesafe_sync", return_value=True),
                self.assertRaises(requests.RequestException),
            ):
                system_one(
                    state="hello",
                    questions=_QUESTIONS,
                    source="test",
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    api_key="",
                    timeout=0.25,
                )
            assert time.monotonic() - started_at < 0.8
        finally:
            server.shutdown()
            server.server_close()

    def test_redirect_body_is_not_read(self) -> None:
        response = _response(302, "redirect body")
        response.headers["Location"] = "https://elsewhere.example.com/systemone"
        with (
            patch("posthog.egress.typesafe.transport.consume_typesafe_sync", return_value=True),
            patch("aiohttp.ClientSession.request", new_callable=AsyncMock, return_value=response) as request,
            self.assertRaises(TypeSafeRequestFailed) as raised,
        ):
            system_one(
                state="hello",
                questions=_QUESTIONS,
                source="test",
                api_key="fake-customer-key",
                base_url="https://decisions.example.com/v1",
            )
        assert raised.exception.status_code == 302
        assert request.call_args.kwargs["allow_redirects"] is False
        assert response.content.read_count == 0

    def test_custom_endpoint_connects_to_the_validated_ip(self) -> None:
        hosts: list[str] = []

        class PinnedEndpoint(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                hosts.append(self.headers["Host"])
                body = json.dumps(_ANSWERS).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), PinnedEndpoint)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("posthog.egress.typesafe.transport.consume_typesafe_sync", return_value=True):
                result = system_one(
                    state="hello",
                    questions=_QUESTIONS,
                    source="test",
                    base_url=f"http://decisions.example.com:{server.server_port}/v1",
                    api_key="",
                    pinned_ip=ip_address("127.0.0.1"),
                )
            assert result.model == "jev-1.13.0"
            assert hosts == [f"decisions.example.com:{server.server_port}"]
        finally:
            server.shutdown()
            server.server_close()

    @parameterized.expand(
        [
            ("no_configured_key", "", "https://api.typesafe.ai/v1", Priority.NORMAL, TypeSafeNotConfigured),
            (
                "critical_lane_skips_the_spend_ceiling",
                _FAKE_API_KEY,
                "https://api.typesafe.ai/v1",
                Priority.CRITICAL,
                ValueError,
            ),
            (
                "custom_endpoint_cannot_inherit_instance_key",
                _FAKE_API_KEY,
                "https://decisions.example.com/v1",
                Priority.NORMAL,
                ValueError,
            ),
        ]
    )
    def test_never_calls_out(
        self, _name: str, api_key: str, base_url: str, priority: Priority, error: type[Exception]
    ) -> None:
        with (
            override_settings(TYPESAFE_API_KEY=api_key),
            patch("aiohttp.ClientSession.request", new_callable=AsyncMock) as request,
            self.assertRaises(error),
        ):
            system_one(state="hi", questions=_QUESTIONS, source="test", priority=priority, base_url=base_url)
        request.assert_not_called()

    @override_settings(TYPESAFE_EGRESS_PER_MINUTE_BUDGET=7, TYPESAFE_EGRESS_HOURLY_BUDGET=11)
    def test_budgets_come_from_the_settings_they_are_named_after(self) -> None:
        assert resolve_policy(typesafe_account_key()).limits == ((7, 60.0), (11, 3600.0))
