from products.aeo.backend.engines import (
    CitationCheck,
    build_check_properties,
    is_target_url,
    parse_anthropic_citations,
    parse_exa_citations,
    parse_openai_responses_citations,
    target_position,
    top_domains,
)

ANTHROPIC_BODY = {
    "id": "msg_01",
    "content": [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "best open source session replay tool"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {"type": "web_search_result", "url": "https://example.com/reviews", "title": "Reviews"},
                {"type": "web_search_result", "url": "https://posthog.com/session-replay", "title": "Session replay"},
            ],
        },
        {
            "type": "text",
            "text": "PostHog offers session replay ",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://posthog.com/session-replay",
                    "title": "Session replay",
                    "cited_text": "...",
                },
            ],
        },
        {
            "type": "text",
            "text": "and other tools exist too.",
            "citations": [
                {"type": "web_search_result_location", "url": "https://example.com/reviews", "title": "Reviews"},
                # Duplicate citation of the same URL must be deduped.
                {"type": "web_search_result_location", "url": "https://posthog.com/session-replay", "title": "SR"},
            ],
        },
    ],
}

ANTHROPIC_ERROR_RESULT_BODY = {
    "content": [
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "q"}},
        # Errored search: content is an object, not a list — must be skipped, not crash.
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": {"type": "web_search_tool_result_error", "error_code": "unavailable"},
        },
        {"type": "text", "text": "I could not search."},
    ],
}

OPENAI_RESPONSES_BODY = {
    "output": [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {"type": "search", "query": "feature flag tools comparison"},
        },
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Several tools offer feature flags.",
                    "annotations": [
                        {"type": "url_citation", "url": "https://posthog.com/feature-flags", "title": "Flags"},
                        {"type": "url_citation", "url": "https://example.com/flags", "title": "Other"},
                        {"type": "url_citation", "url": "https://posthog.com/feature-flags", "title": "dupe"},
                    ],
                }
            ],
        },
    ],
}

EXA_BODY = {
    "answer": "PostHog is one option.",
    "citations": [
        {"id": "https://example.com/a", "url": "https://example.com/a", "title": "A", "publishedDate": "2026-01-01"},
        {"id": "https://docs.posthog.com/x", "url": "https://docs.posthog.com/x", "title": "X"},
    ],
    "costDollars": {"total": 0.005},
    "requestId": "req_1",
}


def test_parse_anthropic_citations() -> None:
    answer, cited, retrieved, queries = parse_anthropic_citations(ANTHROPIC_BODY)
    assert answer == "PostHog offers session replay and other tools exist too."
    assert cited == ["https://posthog.com/session-replay", "https://example.com/reviews"]
    assert retrieved == ["https://example.com/reviews", "https://posthog.com/session-replay"]
    assert queries == ["best open source session replay tool"]


def test_parse_anthropic_error_result_is_skipped() -> None:
    answer, cited, retrieved, queries = parse_anthropic_citations(ANTHROPIC_ERROR_RESULT_BODY)
    assert answer == "I could not search."
    assert cited == []
    assert retrieved == []
    assert queries == ["q"]


def test_parse_openai_responses_citations() -> None:
    answer, cited, queries = parse_openai_responses_citations(OPENAI_RESPONSES_BODY)
    assert answer == "Several tools offer feature flags."
    assert cited == ["https://posthog.com/feature-flags", "https://example.com/flags"]
    assert queries == ["feature flag tools comparison"]


def test_parse_exa_citations() -> None:
    answer, cited, cost = parse_exa_citations(EXA_BODY)
    assert answer == "PostHog is one option."
    assert cited == ["https://example.com/a", "https://docs.posthog.com/x"]
    assert cost == 0.005


def test_is_target_url() -> None:
    domains = ["posthog.com"]
    assert is_target_url("https://posthog.com/docs", domains)
    assert is_target_url("https://www.posthog.com/", domains)
    assert is_target_url("https://docs.posthog.com/x", domains)
    assert not is_target_url("https://notposthog.com/x", domains)
    assert not is_target_url("https://posthog.com.evil.example/x", domains)
    assert not is_target_url("not a url", domains)


def test_target_position() -> None:
    urls = ["https://example.com/a", "https://posthog.com/b", "https://posthog.com/c"]
    assert target_position(urls, ["posthog.com"]) == 2
    assert target_position(["https://example.com/a"], ["posthog.com"]) is None
    assert target_position([], ["posthog.com"]) is None


def test_top_domains_orders_and_dedupes() -> None:
    urls = ["https://a.example.com/1", "https://posthog.com/2", "https://a.example.com/3"]
    assert top_domains(urls) == ["a.example.com", "posthog.com"]


def test_build_check_properties_cited() -> None:
    check = CitationCheck(
        engine="claude-web-search",
        model="claude-sonnet-5",
        cited_urls=["https://example.com/a", "https://posthog.com/session-replay"],
        retrieved_urls=["https://example.com/a"],
        search_queries=["session replay tools"],
        trace_id="trace-1",
    )
    properties = build_check_properties(
        check=check,
        run_id="run-1",
        prompt_id="prompt-1",
        prompt_text="What is the best session replay tool?",
        prompt_source="user_reported",
        prompt_hash="abc",
        target_domains=["posthog.com"],
    )
    assert properties["cited"] is True
    assert properties["check_failed"] is False
    assert properties["target_urls"] == ["https://posthog.com/session-replay"]
    assert properties["target_best_position"] == 2
    assert properties["num_citations"] == 2
    assert properties["gateway_trace_id"] == "trace-1"
    assert "error" not in properties
    assert "cost_usd" not in properties


def test_build_check_properties_failed_check() -> None:
    check = CitationCheck(engine="exa-answer", model="exa-answer", error="HTTPError: status=500 " + "x" * 600)
    properties = build_check_properties(
        check=check,
        run_id="run-1",
        prompt_id="prompt-1",
        prompt_text="q",
        prompt_source="manual",
        prompt_hash="abc",
        target_domains=["posthog.com"],
    )
    assert properties["check_failed"] is True
    assert properties["cited"] is False
    assert len(properties["error"]) <= 500
