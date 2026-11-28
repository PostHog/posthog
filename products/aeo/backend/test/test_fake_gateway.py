import json
import socket
import threading
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.llm.gateway_client import AIGatewayConfig

from products.aeo.backend.dev.fake_gateway import (
    MAX_BODY_BYTES,
    OUTCOME_WEIGHTS,
    Delay,
    FakeGateway,
    FakeGatewayServer,
    engine_outcome,
    parse_delay,
    refuse,
)
from products.aeo.backend.engines import (
    ClaudeWebSearchEngine,
    OpenAIWebSearchEngine,
    PerplexityWebSearchEngine,
    parse_anthropic_citations,
)
from products.aeo.backend.facade.contracts import (
    MAX_SUGGESTED_COMPETITORS,
    KeywordSuggestionRequest,
    PromptSuggestionError,
    PromptSuggestionRequest,
)
from products.aeo.backend.keyword_suggestions import KeywordContext, generate_keyword_suggestions
from products.aeo.backend.suggestions import branded_limit, generate_suggestions, research_site

GATEWAY = AIGatewayConfig(url="http://fake-gateway.test/v1", api_key="phs_fake")
PROMPTS = [
    f"best {thing} for {who}" for thing in ("replay tool", "analytics", "flags", "support desk") for who in range(50)
]


def _route_to(gateway: FakeGateway):
    """A `requests.Session.post` that answers from the fake instead of the network."""

    def post(self: Any, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: Any) -> requests.Response:
        answer = gateway.handle(url.removeprefix(GATEWAY.url.removesuffix("/v1")), json)
        response = requests.Response()
        response.status_code = answer.status
        response.reason = ""
        response.url = url
        response.headers.update(answer.headers)
        response._content = __import__("json").dumps(answer.body).encode()
        return response

    return post


def test_setup_answers_read_through_the_real_setup_parsers() -> None:
    gateway = FakeGateway()
    request = PromptSuggestionRequest(domain="quillnest.com", count=20)
    with (
        patch("products.aeo.backend.suggestions.resolve_ai_gateway_config", return_value=GATEWAY),
        patch("products.aeo.backend.keyword_suggestions.resolve_ai_gateway_config", return_value=GATEWAY),
        patch("products.aeo.backend.llm.requests.Session.post", _route_to(gateway)),
    ):
        research = research_site(1, request)
        found = generate_suggestions(1, request, context_prompts=[], existing_keys=set(), research=research)
        keywords = generate_keyword_suggestions(
            1,
            KeywordSuggestionRequest(domain="quillnest.com", description=research.description, count=20),
            KeywordContext(
                brand_names=("quillnest",),
                competitors=tuple(c.name for c in research.competitors),
                prompts=tuple(p.prompt for p in found.prompts),
                topics=(),
                searches=(("quillnest pricing", "best replay tool"),),
                existing_keywords=frozenset(),
            ),
            count=20,
        )

    assert research.brand == "Quillnest"
    assert research.category and research.description
    assert 1 <= len(research.competitors) <= MAX_SUGGESTED_COMPETITORS
    assert len(found.prompts) == 20
    assert sum(p.branded for p in found.prompts) <= branded_limit(20)
    assert {c.domain for c in found.competitors} == {c.domain for c in research.competitors}
    # The keyword call parses up to the suggestion cap; setup cuts the list to the room left afterwards.
    assert len(keywords) >= 20
    assert all("quillnest" not in k.keyword for k in keywords)
    # The site a setup researched is the one the engine answers cite afterwards.
    assert gateway.domains == ["quillnest.com"]


def test_a_domain_that_asks_to_fail_fails_setup() -> None:
    with (
        patch("products.aeo.backend.suggestions.resolve_ai_gateway_config", return_value=GATEWAY),
        patch("products.aeo.backend.suggestions.TRANSIENT_RETRY_SECONDS", 0),
        patch("products.aeo.backend.llm.requests.Session.post", _route_to(FakeGateway())),
        pytest.raises(PromptSuggestionError, match="Reading your site failed"),
    ):
        research_site(1, PromptSuggestionRequest(domain="fail.example.com"))


@pytest.mark.parametrize("engine_class", [ClaudeWebSearchEngine, OpenAIWebSearchEngine, PerplexityWebSearchEngine])
def test_engine_answers_cover_every_check_state_and_read_through_the_engines(engine_class: type) -> None:
    gateway = FakeGateway()
    gateway.remember_domain("quillnest.com")
    with (
        patch("products.aeo.backend.engines.resolve_ai_gateway_config", return_value=GATEWAY),
        patch("products.aeo.backend.engines.GATEWAY_BACKOFF", MagicMock()),
        patch("products.aeo.backend.engines.requests.Session.post", _route_to(gateway)),
    ):
        engine = engine_class()
        checks = [engine.run(prompt, trace_id="t", custom_properties={}) for prompt in PROMPTS[:60]]

    states = set()
    for check in checks:
        if check.error is not None:
            states.add("failed")
            continue
        assert check.answer_text
        assert 2 <= len(check.cited_urls) <= 6
        assert 1 <= len(check.search_queries) <= 3
        assert all("utm_source" not in url for url in check.cited_urls)
        cited = any(url.startswith("https://quillnest.com") for url in check.cited_urls)
        states.add("cited" if cited else "not cited")
        if cited or "Quillnest" in check.answer_text:
            assert "Quillnest" in check.answer_text
    assert states == {"cited", "not cited", "failed"}


def test_answers_are_the_same_for_the_same_request_and_differ_between_prompts() -> None:
    gateway = FakeGateway()
    body = {"model": "gpt-6-luna", "input": "best replay tool for 1", "tools": [{"type": "web_search"}]}
    # The two calls straddle a second, so an answer that stamps the wall clock would differ.
    with patch("products.aeo.backend.dev.fake_gateway.time.time", side_effect=[1000.0, 2000.0, 3000.0]):
        first = gateway.handle("/v1/responses", body)
        second = gateway.handle("/v1/responses", body)
        other = gateway.handle("/v1/responses", {**body, "input": "best replay tool for 2"})

    assert first.body == second.body
    assert first.body["output"] != other.body["output"]
    # Every outcome is reachable from a prompt, and the same prompt lands on the same one each time.
    assert {engine_outcome(prompt, "gpt-6-luna") for prompt in PROMPTS} == set(OUTCOME_WEIGHTS)
    assert engine_outcome("best replay tool for 1", "gpt-6-luna") == engine_outcome(
        "best replay tool for 1", "gpt-6-luna"
    )


def test_the_server_answers_over_http() -> None:
    server = FakeGatewayServer(("127.0.0.1", 0), quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = {"model": "claude-sonnet-5", "max_tokens": 10, "messages": [{"role": "user", "content": "best tool"}]}
        answered = requests.post(f"{base}/v1/messages", json=body, timeout=5)
        health = requests.get(base, timeout=5)
        unknown = requests.post(f"{base}/v1/chat/completions", json=body, timeout=5)
        from_a_page = requests.post(
            f"{base}/v1/messages", json=body, headers={"Origin": "https://evil.example"}, timeout=5
        )
        oversized = _post_declaring(server.server_address[1], str(MAX_BODY_BYTES + 1))
        unbounded = _post_declaring(server.server_address[1], "-1")
        endless = _post_declaring(server.server_address[1], "9" * 5000)
    finally:
        server.shutdown()
        server.server_close()

    assert health.json()["mode"] == "generated"
    assert unknown.status_code == 404
    assert from_a_page.status_code == 403
    assert oversized.startswith(b"HTTP/1.1 413")
    assert unbounded.startswith(b"HTTP/1.1 400")
    assert endless.startswith(b"HTTP/1.1 413")
    assert answered.headers["X-Fake-Gateway"] == "generated"
    if answered.status_code == 200:
        assert parse_anthropic_citations(answered.json()).answer_text
    else:
        assert answered.status_code in (400, 429)
        assert json.loads(answered.content)["error"]["message"]


def _post_declaring(port: int, content_length: str) -> bytes:
    """A POST whose headers promise a body that never comes; the answer must arrive without it."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(
            f"POST /v1/messages HTTP/1.1\r\nHost: fake\r\nContent-Type: application/json\r\n"
            f"Content-Length: {content_length}\r\n\r\n".encode()
        )
        return sock.recv(4096)


@pytest.mark.parametrize(
    "headers, record_key, status",
    [
        ({"Content-Length": "10"}, None, None),
        ({"content-length": " 10 ", "Authorization": "Bearer s3cret"}, "s3cret", None),
        ({"Content-Length": "10", "Authorization": "Bearer phs_fake"}, "s3cret", 401),
        ({"Content-Length": "10"}, "s3cret", 401),
        ({"Content-Length": "10", "Origin": "https://evil.example", "Authorization": "Bearer s3cret"}, "s3cret", 403),
        ({"Content-Length": "10", "Sec-Fetch-Mode": "cors"}, None, 403),
        ({"Content-Length": str(MAX_BODY_BYTES + 1)}, None, 413),
        ({"Content-Length": "-1"}, None, 400),
        ({"Content-Length": "+10"}, None, 400),
        ({"Content-Length": "1e3"}, None, 400),
        ({"Content-Length": "lots"}, None, 400),
        ({"Content-Length": "9" * 5000}, None, 413),
        ({}, None, 400),
    ],
)
def test_refusals(headers: dict[str, str], record_key: str | None, status: int | None) -> None:
    refused = refuse(headers, record_key)
    assert (refused.status if refused else None) == status


def _plain_post(port: int, path: str, body: dict[str, Any], headers: dict[str, str]) -> HTTPResponse:
    """A client that does not go through `requests`, which the recorder under test has patched."""
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json", **headers})
    response = connection.getresponse()
    response.read_body = response.read()  # type: ignore[attr-defined]
    return response


def _recorded_response(status: int, body: dict[str, Any], headers: dict[str, str]) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers)
    response._content = json.dumps(body).encode()
    return response


def test_record_mode_forwards_only_with_the_key_and_replay_cites_the_recorded_site(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"gateway_url": "https://gateway.example/v1", "token": "phs_not_a_real_token"}))
    store = tmp_path / "store"
    research = {
        "model": "claude-haiku-5-5",
        "max_tokens": 10,
        "messages": [
            {"role": "user", "content": "You research a company. Read quillnest.com itself first.\nSite: quillnest.com"}
        ],
    }
    cited_prompt = next(prompt for prompt in PROMPTS if engine_outcome(prompt, "claude-sonnet-5") == "cited")
    check = {
        "model": "claude-sonnet-5",
        "max_tokens": 10,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": cited_prompt}],
    }
    upstream = _recorded_response(
        200, {"id": "msg_1", "content": [{"type": "text", "text": "{}"}]}, {"X-PostHog-Denial": "none"}
    )
    seen: list[dict[str, Any]] = []

    def post(url: str, *, data: bytes, headers: dict[str, str], timeout: Any) -> requests.Response:
        seen.append({"url": url, "headers": headers})
        return upstream

    recorder = FakeGatewayServer(
        ("127.0.0.1", 0), mode="record", store=store, quiet=True, record_key="s3cret", token_file=token_file
    )
    thread = threading.Thread(target=recorder.serve_forever, daemon=True)
    thread.start()
    port = recorder.server_address[1]
    try:
        with patch("products.aeo.backend.dev.fake_gateway.requests.post", post):
            unauthenticated = _plain_post(port, "/v1/messages", research, {})
            recorded = _plain_post(port, "/v1/messages", research, {"Authorization": "Bearer s3cret"})
    finally:
        recorder.shutdown()
        recorder.server_close()

    assert unauthenticated.status == 401
    assert recorded.status == 200
    assert recorded.getheader("X-PostHog-Denial") == "none"
    assert len(seen) == 1
    assert seen[0]["url"] == "https://gateway.example/v1/messages"
    assert seen[0]["headers"]["Authorization"] == "Bearer phs_not_a_real_token"
    assert b"phs_not_a_real_token" not in recorded.read_body  # type: ignore[attr-defined]
    assert list(store.glob("*.part")) == []

    replayer = FakeGatewayServer(("127.0.0.1", 0), mode="replay", store=store, quiet=True)
    try:
        replayed, mode = replayer.answer("/v1/messages", research, {})
        generated, generated_mode = replayer.answer("/v1/messages", check, {})
    finally:
        replayer.server_close()
    assert (replayed.body, mode) == (upstream.json(), "replay")
    assert generated_mode == "generated"
    assert replayer.gateway.domains == ["quillnest.com"]
    assert any(url.startswith("https://quillnest.com") for url in parse_anthropic_citations(generated.body).cited_urls)


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("", Delay()),
        ("500", Delay(low=0.5, high=0.5)),
        ("800-3000", Delay(low=0.8, high=3.0)),
        ("3000-800", Delay(low=3.0, high=3.0)),
    ],
)
def test_delay_specs(spec: str, expected: Delay) -> None:
    assert parse_delay(spec) == expected
