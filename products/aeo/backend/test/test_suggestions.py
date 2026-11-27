import json
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.aeo.backend.facade.contracts import (
    FunnelStage,
    PromptCircle,
    PromptSuggestionError,
    PromptSuggestionRequest,
    SuggestedCompetitor,
)
from products.aeo.backend.llm import ask_with_web_search
from products.aeo.backend.suggestions import (
    UNREADABLE_ANSWER_ERROR,
    SiteResearch,
    SuggestedPromptSet,
    build_suggestion_instructions,
    mix_counts,
    parse_competitors,
    parse_suggestions,
    prompt_key,
    suggest_prompts,
)


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


@pytest.mark.parametrize("count", [1, 3, 7, 20, 50])
def test_the_mix_always_adds_up_to_the_count(count: int) -> None:
    mix = mix_counts(count)

    assert sum(n for _, n in mix) == count
    assert all(abs(n - count * pattern.share) < 1 for pattern, n in mix)


def test_instructions_after_research_write_the_mix_from_it_without_searching_again() -> None:
    research = SiteResearch(
        brand="Hedgebox", category="file storage", description="Stores and shares files.", competitors=()
    )

    instructions = build_suggestion_instructions(
        PromptSuggestionRequest(domain="hedgebox.net", count=20), [], research=research
    )

    assert "Category: file storage" in instructions
    assert "Research first" not in instructions
    assert '8 best-of prompts, such as "best file storage tool"' in instructions
    assert '3 comparison prompts that name Hedgebox, such as "Hedgebox vs <competitor>"' in instructions


def _status(code: int, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock(status_code=code, headers=headers or {})
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


def _response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = {"stop_reason": stop_reason, "content": [{"type": "text", "text": text}]}
    return response


COMPETITORS = [
    {"name": "Dropbox", "domain": "https://www.dropbox.com"},
    {"name": "Hedgebox", "domain": "hedgebox.net"},
    {"name": "Box", "domain": "box.com"},
    {"name": "No site", "domain": "not a domain"},
]


@parameterized.expand(
    [
        ("object", json.dumps({"competitors": COMPETITORS, "prompts": [_item("A?"), _item("B?")]}), "end_turn"),
        ("bare_array", json.dumps([_item("A?"), _item("B?")]), "end_turn"),
        (
            "object_cut_off_mid_prompt",
            json.dumps({"competitors": COMPETITORS, "prompts": [_item("A?"), _item("B?"), _item("C?")]})[:-40],
            "max_tokens",
        ),
        (
            "array_cut_off_after_bracketed_commentary",
            "See [the docs](https://example.com) [1].\n" + json.dumps([_item("A?"), _item("B?"), _item("C?")])[:-40],
            "max_tokens",
        ),
    ]
)
def test_answer_reads_as_an_object_or_an_array_even_when_cut_off(_name: str, text: str, stop_reason: str) -> None:
    with patch("products.aeo.backend.llm.requests.Session.post", return_value=_response(text, stop_reason)):
        answer = ask_with_web_search(
            MagicMock(url="http://gateway", api_key="key"),
            "instructions",
            team_id=1,
            trace_id="trace",
            aeo_feature="prompt_suggestions",
            max_tokens=100,
            max_searches=1,
        )
    assert answer is not None

    assert [s.prompt for s in parse_suggestions(answer.text, count=10, existing_keys=set())] == ["A?", "B?"]
    assert parse_competitors(answer.text, own_domain="hedgebox.net") == (
        [SuggestedCompetitor(name="Dropbox", domain="dropbox.com"), SuggestedCompetitor(name="Box", domain="box.com")]
        if text.lstrip().startswith("{")
        else []
    )


class TestSuggestPrompts(BaseTest):
    def _suggest(self, answers: list[str], **request: Any) -> tuple[SuggestedPromptSet, MagicMock]:
        post = MagicMock(side_effect=[_response(answer) for answer in answers])
        with (
            patch(
                "products.aeo.backend.suggestions.resolve_ai_gateway_config",
                return_value=MagicMock(url="http://gateway", api_key="key"),
            ),
            patch("products.aeo.backend.llm.requests.Session.post", post),
        ):
            found = suggest_prompts(self.team.id, PromptSuggestionRequest(domain="hedgebox.net", **request))
        return found, post

    @staticmethod
    def _instructions(post: MagicMock, call: int) -> str:
        return post.call_args_list[call].kwargs["json"]["messages"][0]["content"]

    def _suggest_with(self, side_effect: list) -> tuple[SuggestedPromptSet, MagicMock]:
        post = MagicMock(side_effect=side_effect)
        with (
            patch(
                "products.aeo.backend.suggestions.resolve_ai_gateway_config",
                return_value=MagicMock(url="http://gateway", api_key="key"),
            ),
            patch("products.aeo.backend.llm.requests.Session.post", post),
            patch("products.aeo.backend.suggestions.TRANSIENT_RETRY_SECONDS", 0),
        ):
            found = suggest_prompts(self.team.id, PromptSuggestionRequest(domain="hedgebox.net", count=1))
        return found, post

    def test_a_rate_limited_call_is_asked_again_once(self) -> None:
        found, post = self._suggest_with(
            [_status(429), _response(json.dumps({"competitors": [], "prompts": [_item("A?")]}))]
        )

        assert [s.prompt for s in found.prompts] == ["A?"]
        assert post.call_count == 2

    @parameterized.expand(
        [
            ("spend limit", {}, "spend limit"),
            ("credit refusal", {"X-PostHog-Denial": "credit_bucket_exhausted"}, "AI credit usage limit"),
        ]
    )
    def test_a_402_is_not_retried_and_says_why(self, _name: str, headers: dict[str, str], message: str) -> None:
        with pytest.raises(PromptSuggestionError, match=message):
            self._suggest_with([_status(402, headers), _status(402, headers)])

    def test_an_unreadable_answer_is_asked_again_once(self) -> None:
        found, post = self._suggest(
            ["Let me research first.", json.dumps({"competitors": [], "prompts": [_item("A?")]})], count=1
        )

        assert [s.prompt for s in found.prompts] == ["A?"]
        assert post.call_count == 2

    def test_a_second_unreadable_answer_fails_with_the_readable_error(self) -> None:
        with pytest.raises(PromptSuggestionError, match=UNREADABLE_ANSWER_ERROR):
            self._suggest(["no json", "still no json"], count=1)

    def test_a_short_answer_tops_up_once_with_the_suggested_prompts_as_tracked(self) -> None:
        first = json.dumps({"competitors": COMPETITORS[:1], "prompts": [_item("A?"), _item("B?")]})
        top_up = json.dumps({"competitors": [], "prompts": [_item("A?"), _item("C?")]})

        found, post = self._suggest([first, top_up], count=5)

        assert [s.prompt for s in found.prompts] == ["A?", "B?", "C?"]
        assert found.competitors == (SuggestedCompetitor(name="Dropbox", domain="dropbox.com"),)
        assert post.call_count == 2
        top_up_instructions = self._instructions(post, 1)
        assert "write 3 prompts" in top_up_instructions
        assert "- A?\n- B?" in top_up_instructions
        assert "Competitors: Dropbox" in top_up_instructions

    def test_a_failed_top_up_keeps_the_first_prompts(self) -> None:
        found, post = self._suggest([json.dumps([_item("A?")]), "no json"], count=5)

        assert [s.prompt for s in found.prompts] == ["A?"]
        assert post.call_count == 2

    def test_prompts_naming_the_brand_are_capped_whatever_their_label(self) -> None:
        plain = [_item(f"Best file sharing tool {i}?") for i in range(8)]
        branded = [
            _item("Is Hedgebox any good?"),
            _item("What is Hedgebox?", circle="branded", branded=True),
            _item("Hedgebox vs Dropbox?"),
            _item("How much does hedgebox cost?"),
        ]

        found, post = self._suggest([json.dumps(branded[:1] + plain[:4] + branded[1:] + plain[4:])], count=10)

        assert [s.prompt for s in found.prompts if s.branded] == ["Is Hedgebox any good?", "What is Hedgebox?"]
        assert len(found.prompts) == 10
        assert post.call_count == 1

    def test_competitors_given_in_the_request_come_back(self) -> None:
        found, _ = self._suggest(
            [json.dumps({"competitors": COMPETITORS, "prompts": [_item("A?")]})],
            count=1,
            competitors=("Dropbox", "pcloud.com", "Sync"),
        )

        assert found.competitors == (
            SuggestedCompetitor(name="Dropbox", domain="dropbox.com"),
            SuggestedCompetitor(name="Pcloud", domain="pcloud.com"),
            SuggestedCompetitor(name="Sync", domain=""),
        )
