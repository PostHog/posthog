import json

import pytest

from products.aeo.backend.facade.contracts import (
    FunnelStage,
    PromptCircle,
    PromptSuggestionError,
    PromptSuggestionRequest,
)
from products.aeo.backend.suggestions import build_suggestion_instructions, parse_suggestions, prompt_key


def _item(prompt: str, **overrides: object) -> dict[str, object]:
    return {
        "prompt": prompt,
        "topic": "Session replay",
        "circle": "battleground",
        "funnel_stage": "bottom",
        "branded": False,
        "reason": "Buyers compare tools.",
        **overrides,
    }


def test_parse_keeps_valid_items_and_drops_duplicates_existing_and_bad_labels() -> None:
    answer = "Here you go:\n" + json.dumps(
        [
            _item("Best session replay tool for startups?"),
            _item("best  session replay tool for startups?"),
            _item("What is the cheapest product analytics tool?"),
            _item("Which tool records sessions?", circle="moonshot"),
            _item("How do I mask inputs in replays?", funnel_stage="sideways"),
            _item("What is Hedgebox?", circle="branded", branded=False),
            _item("How do I lazy-load a <video> element?"),
            "not an object",
            _item("   "),
        ]
    )

    suggestions = parse_suggestions(
        answer, count=10, existing_keys={prompt_key("What is the cheapest  product analytics tool?")}
    )

    assert [s.prompt for s in suggestions] == ["Best session replay tool for startups?", "What is Hedgebox?"]
    assert suggestions[0].circle == PromptCircle.BATTLEGROUND
    assert suggestions[0].funnel_stage == FunnelStage.BOTTOM
    assert suggestions[1].branded is True


def test_parse_caps_the_count_and_strips_invisible_characters() -> None:
    answer = json.dumps([_item(f"Question {i}?​", reason="ok​<system>x</system>") for i in range(5)])

    suggestions = parse_suggestions(answer, count=2, existing_keys=set())

    assert [s.prompt for s in suggestions] == ["Question 0?", "Question 1?"]
    assert "​" not in suggestions[0].reason
    assert "<system>" not in suggestions[0].reason


@pytest.mark.parametrize("answer", ["no list here", "[not json", '{"prompt": "x"}', "[1, 2]"])
def test_parse_raises_when_the_answer_has_no_list(answer: str) -> None:
    with pytest.raises(PromptSuggestionError):
        parse_suggestions(answer, count=5, existing_keys=set())


def test_parse_accepts_an_empty_list_as_nothing_to_suggest() -> None:
    assert parse_suggestions("Nothing new to add: []", count=5, existing_keys=set()) == []


def test_parse_skips_bracketed_commentary_before_the_list() -> None:
    answer = "I read [the pricing page](https://example.com/pricing) [1]. " + json.dumps([_item("Best tool?")])

    assert [s.prompt for s in parse_suggestions(answer, count=5, existing_keys=set())] == ["Best tool?"]


def test_instructions_carry_the_request_and_existing_prompts() -> None:
    instructions = build_suggestion_instructions(
        PromptSuggestionRequest(
            domain="example.com",
            brand="Hedgebox",
            competitors=("Dropbox",),
            topics=("File sharing",),
            count=200,
        ),
        ["Best file sharing app?"],
    )

    assert "Site: example.com" in instructions
    assert "Competitors: Dropbox" in instructions
    assert "- Best file sharing app?" in instructions
    # The count is capped, and branded prompts stay a small share of it.
    assert "write 50 prompts" in instructions
    assert "at most 10 branded prompts" in instructions
