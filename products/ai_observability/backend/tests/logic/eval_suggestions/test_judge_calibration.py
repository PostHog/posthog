import re
import json
import time
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai
import anthropic
from anthropic.types import ToolUseBlock, Usage
from parameterized import parameterized

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.logic.eval_suggestions import call_review, judge_calibration
from products.ai_observability.backend.logic.eval_suggestions.call_review_queries import CallTypeRow, ReviewCallRow
from products.ai_observability.backend.logic.eval_suggestions.judge_calibration import Calibration
from products.ai_observability.backend.logic.eval_suggestions.prices import MODEL_PRICES

SUPPORT = CallTypeRow(source="prompt_name", name="support-reply", calls=900, model="gpt-5-mini", example_input="[]")
JUDGE_PROMPT = "Does the reply avoid promising a refund date?"
REQUEST = httpx.Request("POST", "https://gateway.example.com")


@parameterized.expand(
    [
        ("catches_three_in_five", 5, 3, 0, 30, True),
        ("catches_two_in_five", 5, 2, 0, 30, False),
        ("one_false_alarm_per_two_fails", 10, 6, 5, 30, True),
        ("one_false_alarm_too_many", 10, 6, 6, 30, False),
        ("one_false_alarm_always_allowed", 3, 2, 1, 30, True),
        ("two_false_alarms_on_three_fails", 3, 2, 2, 30, False),
        ("nothing_to_catch", 0, 0, 0, 30, False),
        ("enough_passes_judged", 5, 3, 0, 5, True),
        ("passes_unjudged_are_not_clean", 5, 3, 0, 4, False),
    ]
)
def test_a_card_is_kept_only_when_its_judge_agrees_with_the_review(
    _name: str, review_fails: int, caught: int, false_alarms: int, judged_passes: int, kept: bool
) -> None:
    calibration = Calibration(
        review_fails=review_fails,
        caught=caught,
        review_passes=30,
        judged_passes=judged_passes,
        false_alarms=false_alarms,
        unjudged=30 - judged_passes,
    )

    assert judge_calibration.keeps(calibration) is kept


@parameterized.expand(
    [
        ("fails_and_passes_share_the_slots", 40, 30, 20, 20),
        ("few_fails_leave_their_slots_to_passes", 5, 45, 5, 35),
        ("few_passes_leave_their_slots_to_fails", 45, 3, 37, 3),
    ]
)
def test_calibration_keeps_room_for_the_review_passes(
    _name: str, fails: int, passes: int, picked_fails: int, picked_passes: int
) -> None:
    labels = dict.fromkeys(range(1, fails + 1), "fail") | dict.fromkeys(range(fails + 1, fails + passes + 1), "pass")
    card = MagicMock(labels=labels)

    numbers = judge_calibration.calibration_calls(card)

    assert sum(1 for n in numbers if labels[n] == "fail") == picked_fails
    assert sum(1 for n in numbers if labels[n] == "pass") == picked_passes


def _card_and_rendering() -> tuple[call_review.ReviewCard, call_review.Rendering]:
    rows = [
        ReviewCallRow(
            event_uuid=f"e{index}",
            trace_id=f"support-{index}",
            call_type=SUPPORT.key,
            input=json.dumps(
                [{"role": "system", "content": "Never promise a date."}, {"role": "user", "content": "?"}]
            ),
            output=json.dumps(f"Reply {index}"),
        )
        for index in range(50)
    ]
    rendering = call_review.render([SUPPORT], call_review.select_calls(rows))
    card = call_review.parse_cards(
        {
            "cards": [
                {
                    "title": "Replies promise refund dates",
                    "checks": "Checks whether a reply promises a refund date",
                    "why": "The prompt says never to promise a date.",
                    "call_types": ["T1"],
                    "labels": [{"call": n, "verdict": "fail" if n <= 5 else "pass"} for n in range(1, 51)],
                    "examples": [{"trace_id": "support-0", "what_went_wrong": "Promised Friday"}],
                    "judge_prompt": JUDGE_PROMPT,
                }
            ]
        },
        rendering,
    )[0]
    return card, rendering


def _anthropic_reply(verdict: str) -> MagicMock:
    return MagicMock(
        content=[
            ToolUseBlock(
                id="toolu_1", name="record_verdict", input={"reasoning": "r", "verdict": verdict}, type="tool_use"
            )
        ],
        usage=Usage(input_tokens=1000, output_tokens=50),
    )


def _openai_reply(verdict: str) -> MagicMock:
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({"reasoning": "r", "verdict": verdict})))],
        usage=MagicMock(prompt_tokens=1000, completion_tokens=50),
    )


@parameterized.expand(
    [
        ("anthropic", anthropic.Anthropic, _anthropic_reply, anthropic.APIConnectionError(request=REQUEST)),
        ("openai", openai.OpenAI, _openai_reply, openai.APIConnectionError(request=REQUEST)),
    ]
)
def test_the_judge_grades_the_review_calls_on_the_team_model(
    provider: str, sdk: type, reply: Any, connection_reset: Exception
) -> None:
    card, rendering = _card_and_rendering()
    model = DEFAULT_MODEL_BY_PROVIDER[provider]
    numbers = judge_calibration.calibration_calls(card)
    requests = [judge_calibration.judge_request(card, rendering, number, model) for number in numbers]
    prompts: list[str] = []

    def answer(**kwargs: Any) -> MagicMock:
        prompt = kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        match = re.search(r'<call number="(\d+)"', prompt)
        assert match is not None
        number = int(match.group(1))
        if number == 3:
            raise connection_reset
        return reply("fail" if number in (1, 2, 4, 6, 7) else "pass")

    client = MagicMock(spec=sdk)
    create = client.messages.create if provider == "anthropic" else client.chat.completions.create
    create.side_effect = answer

    with patch.object(call_review, "RETRY_BACKOFF_SECONDS", 0):
        calls = judge_calibration.judge_all(client, requests, deadline=None)
    calibration = judge_calibration.calibrate(card, numbers, [call.verdict if call else None for call in calls])

    # Every fail and the first 35 passes, each sent as the review rendered it, with the judge prompt.
    assert numbers == list(range(1, 41))
    assert sorted(set(prompts)) == sorted(rendering.calls[number].text for number in numbers)
    assert all(JUDGE_PROMPT in request.system for request in requests)
    assert calibration == Calibration(
        review_fails=5, caught=3, review_passes=35, judged_passes=35, false_alarms=2, unjudged=1
    )
    assert judge_calibration.keeps(calibration)
    # The judge's 2 false alarms in 35 passes stand for all 45: 3 + 2 * 45 / 35 rounds to 6 of 50.
    assert (judge_calibration.measured(card, calibration).failed, card.of) == (6, 50)
    # The reset call used every attempt and counts at its most, since a reset may have billed.
    price = MODEL_PRICES[model]
    served = 1000 * price.input_per_token + 50 * price.output_per_token
    assert len(prompts) == 39 + call_review.ATTEMPTS
    assert sum(call.cost_usd for call in calls if call) == pytest.approx(
        39 * served + judge_calibration.max_cost_usd([requests[2]])
    )


def test_a_request_that_could_end_past_the_deadline_never_starts() -> None:
    card, rendering = _card_and_rendering()
    client = MagicMock(spec=anthropic.Anthropic)

    calls = judge_calibration.judge_all(
        client, [judge_calibration.judge_request(card, rendering, 1, "claude-haiku-4-5")], deadline=time.monotonic()
    )

    assert calls == [None]
    client.messages.create.assert_not_called()
