import json
import threading
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.llm.gateway_client import AIGatewayConfig

from products.aeo.backend.dev.fake_gateway import (
    OUTCOME_WEIGHTS,
    FakeGateway,
    FakeGatewayServer,
    engine_outcome,
    parse_delay,
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
    body = {"model": "gpt-5", "input": "best replay tool for 1", "tools": [{"type": "web_search"}]}
    first = gateway.handle("/v1/responses", body)
    second = gateway.handle("/v1/responses", body)
    other = gateway.handle("/v1/responses", {**body, "input": "best replay tool for 2"})

    assert first.body == second.body
    assert first.body["output"] != other.body["output"]
    # Every outcome is reachable from a prompt, and the same prompt lands on the same one each time.
    assert {engine_outcome(prompt, "gpt-5") for prompt in PROMPTS} == set(OUTCOME_WEIGHTS)
    assert engine_outcome("best replay tool for 1", "gpt-5") == engine_outcome("best replay tool for 1", "gpt-5")


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
    finally:
        server.shutdown()
        server.server_close()

    assert health.json()["mode"] == "generated"
    assert unknown.status_code == 404
    assert answered.headers["X-Fake-Gateway"] == "generated"
    if answered.status_code == 200:
        assert parse_anthropic_citations(answered.json()).answer_text
    else:
        assert answered.status_code in (400, 429)
        assert json.loads(answered.content)["error"]["message"]


@pytest.mark.parametrize(
    "spec, expected",
    [("", (0.0, 0.0)), ("500", (0.5, 0.5)), ("800-3000", (0.8, 3.0)), ("3000-800", (3.0, 3.0))],
)
def test_delay_specs(spec: str, expected: tuple[float, float]) -> None:
    assert parse_delay(spec) == expected
