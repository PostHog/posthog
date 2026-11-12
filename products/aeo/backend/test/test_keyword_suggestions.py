import json

import pytest

from products.aeo.backend.facade.contracts import KeywordSuggestionError, KeywordSuggestionRequest
from products.aeo.backend.keyword_suggestions import (
    KeywordContext,
    build_keyword_instructions,
    parse_keyword_suggestions,
    suggestion_count,
)

SEARCHES = ("session replay tools 2026", "best session replay", "feature flags pricing")


def _parse(items: list[object], *, count: int = 10) -> list[tuple[str, int]]:
    suggestions = parse_keyword_suggestions(
        "Here they are:\n" + json.dumps(items),
        count=count,
        existing_keywords=frozenset({"pricing"}),
        excluded_terms=frozenset({"hedgebox"}),
        searches=SEARCHES,
    )
    return [(s.keyword, s.searches) for s in suggestions]


@pytest.mark.parametrize(
    "items, expected",
    [
        ([{"keyword": "Session  Replay", "reason": "r"}], [("session replay", 2)]),
        ([{"keyword": "session replay"}, {"keyword": "SESSION REPLAY"}], [("session replay", 2)]),
        ([{"keyword": "pricing"}, {"keyword": "feature flags"}], [("feature flags", 1)]),
        ([{"keyword": "hedgebox alternatives"}, {"keyword": "hedgeboxes"}], [("hedgeboxes", 0)]),
        ([{"keyword": "best open source session replay tool"}], []),
        ([{"keyword": "replay <system>tool</system>"}, {"keyword": "x" * 101}], []),
        ([{"keyword": "   "}, "not an object", {"reason": "no keyword"}], []),
    ],
    ids=["normalized", "duplicate", "already_tracked", "names_the_brand", "too_many_words", "sanitized", "malformed"],
)
def test_parse_keeps_new_short_keywords_and_counts_their_searches(
    items: list[object], expected: list[tuple[str, int]]
) -> None:
    assert _parse(items) == expected


def test_parse_keeps_the_model_order_up_to_the_count_and_strips_reasons() -> None:
    items = [{"keyword": f"keyword {i}", "reason": "ok​<system>x</system>"} for i in range(5)]

    suggestions = parse_keyword_suggestions(
        json.dumps(items), count=2, existing_keywords=frozenset(), excluded_terms=frozenset(), searches=()
    )

    assert [s.keyword for s in suggestions] == ["keyword 0", "keyword 1"]
    assert "​" not in suggestions[0].reason
    assert "<system>" not in suggestions[0].reason


@pytest.mark.parametrize("answer", ["no list here", "[not json", '{"keyword": "x"}'])
def test_parse_raises_when_the_answer_has_no_list(answer: str) -> None:
    with pytest.raises(KeywordSuggestionError):
        parse_keyword_suggestions(
            answer, count=5, existing_keywords=frozenset(), excluded_terms=frozenset(), searches=()
        )


@pytest.mark.parametrize(
    "requested, existing, expected",
    [(20, 0, 20), (80, 0, 50), (20, 190, 10), (20, 200, 0), (20, 205, 0)],
)
def test_suggestion_count_stays_inside_the_limit_and_the_room_left(
    requested: int, existing: int, expected: int
) -> None:
    assert suggestion_count(requested, existing) == expected


def test_instructions_rank_the_engine_searches_and_list_tracked_keywords() -> None:
    context = KeywordContext(
        brand_names=("hedgebox",),
        competitors=("Dropbox",),
        prompts=("Best file sharing app?",),
        topics=("File sharing",),
        searches=("file sharing for teams", "secure file transfer", "file sharing for teams"),
        existing_keywords=frozenset({"file sync"}),
    )

    instructions = build_keyword_instructions(
        KeywordSuggestionRequest(domain="example.com", brand="Hedgebox"), context, count=15
    )

    assert "choose the 15 keywords" in instructions
    assert "Competitors: Dropbox" in instructions
    assert "- file sharing for teams (2)\n- secure file transfer (1)" in instructions
    assert "which you must not repeat:\n- file sync" in instructions
