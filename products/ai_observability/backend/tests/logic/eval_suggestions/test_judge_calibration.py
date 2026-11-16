import re
import json
import time
from dataclasses import replace
from operator import attrgetter
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai
import anthropic
from anthropic.types import ToolUseBlock, Usage
from google import genai
from google.genai import errors as genai_errors
from parameterized import parameterized

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.logic.eval_suggestions import call_review, judge_calibration
from products.ai_observability.backend.logic.eval_suggestions.call_review import Verdict
from products.ai_observability.backend.logic.eval_suggestions.call_review_queries import CallTypeRow, ReviewCallRow
from products.ai_observability.backend.logic.eval_suggestions.judge_calibration import Calibration
from products.ai_observability.backend.logic.eval_suggestions.prices import MODEL_PRICES

SUPPORT = CallTypeRow(source="prompt_name", name="support-reply", calls=900, model="gpt-5-mini", example_input="[]")
JUDGE_PROMPT = "Does the reply avoid promising a refund date?"
REQUEST = httpx.Request("POST", "https://gateway.example.com")


@parameterized.expand(
    [
        ("catches_three_in_five", 5, 3, 0, 30, 30, True),
        ("catches_two_in_five", 5, 2, 0, 30, 30, False),
        ("one_false_alarm_per_two_fails", 10, 6, 5, 30, 30, True),
        ("one_false_alarm_too_many", 10, 6, 6, 30, 30, False),
        ("one_false_alarm_always_allowed", 3, 2, 1, 30, 30, True),
        ("two_false_alarms_on_three_fails", 3, 2, 2, 30, 30, False),
        ("nothing_to_catch", 0, 0, 0, 30, 30, False),
        ("enough_passes_judged", 5, 3, 0, 5, 30, True),
        ("passes_unjudged_are_not_clean", 5, 3, 0, 4, 30, False),
        ("false_alarms_scale_to_every_review_pass", 20, 12, 10, 20, 50, False),
    ]
)
def test_a_card_is_kept_only_when_its_judge_agrees_with_the_review(
    _name: str, review_fails: int, caught: int, false_alarms: int, judged_passes: int, passes: int, kept: bool
) -> None:
    labels = dict.fromkeys(range(1, review_fails + 1), "fail") | dict.fromkeys(
        range(review_fails + 1, review_fails + passes + 1), "pass"
    )
    calibration = Calibration(
        review_fails=review_fails,
        caught=caught,
        review_passes=30,
        judged_passes=judged_passes,
        false_alarms=false_alarms,
        unjudged=30 - judged_passes,
        na_on_fails=0,
        na_on_passes=0,
    )

    assert judge_calibration.keeps(MagicMock(labels=labels, of=review_fails + passes), calibration) is kept


@parameterized.expand(
    [
        ("fails_and_passes_share_the_slots", 40, 30, 0, 20, 20),
        ("few_fails_leave_their_slots_to_passes", 5, 45, 0, 5, 35),
        ("few_passes_leave_their_slots_to_fails", 45, 3, 0, 37, 3),
        ("calls_the_question_skips_take_pass_slots", 10, 5, 40, 10, 30),
    ]
)
def test_calibration_keeps_room_for_the_review_passes(
    _name: str, fails: int, passes: int, na: int, picked_fails: int, picked_passes: int
) -> None:
    verdicts = ["fail"] * fails + ["pass"] * passes + ["na"] * na
    labels = dict(enumerate(verdicts, start=1))
    card = MagicMock(labels=labels)

    numbers = judge_calibration.calibration_calls(card)

    assert sum(1 for n in numbers if labels[n] == "fail") == picked_fails
    assert sum(1 for n in numbers if labels[n] != "fail") == picked_passes


@parameterized.expand([("answers_na", "na", True), ("fails_them", "fail", False)])
def test_a_judge_must_not_fail_calls_the_question_does_not_apply_to(_name: str, on_na: Verdict, kept: bool) -> None:
    labels: dict[int, Verdict] = {n: "fail" if n <= 5 else "pass" if n <= 15 else "na" for n in range(1, 46)}
    card = replace(_card_and_rendering()[0], labels=labels, failed=5, of=15)
    numbers = judge_calibration.calibration_calls(card)

    calibration = judge_calibration.calibrate(
        card, numbers, [on_na if labels[n] == "na" else labels[n] for n in numbers]
    )

    assert judge_calibration.keeps(card, calibration) is kept
    # The judge saw 35 of the review's 40 other calls, so each verdict on one of them stands for 40 / 35 calls.
    measured = judge_calibration.measured(card, calibration)
    assert (measured.failed, measured.of) == ((5, 16) if kept else (34, 45))


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


def _gemini_reply(verdict: str) -> MagicMock:
    return MagicMock(
        text=json.dumps({"reasoning": "r", "verdict": verdict}),
        usage_metadata=MagicMock(prompt_token_count=1000, candidates_token_count=30, thoughts_token_count=20),
    )


@parameterized.expand(
    [
        (
            "anthropic",
            anthropic.Anthropic,
            "messages.create",
            _anthropic_reply,
            anthropic.APIConnectionError(request=REQUEST),
        ),
        ("openai", openai.OpenAI, "chat.completions.create", _openai_reply, openai.APIConnectionError(request=REQUEST)),
        ("gemini", genai.Client, "models.generate_content", _gemini_reply, httpx.ConnectError("Connection reset")),
    ]
)
def test_the_judge_grades_the_review_calls_on_the_team_model(
    provider: str, sdk: type, method: str, reply: Any, connection_reset: Exception
) -> None:
    card, rendering = _card_and_rendering()
    model = DEFAULT_MODEL_BY_PROVIDER[provider]
    numbers = judge_calibration.calibration_calls(card)
    requests = [judge_calibration.judge_request(card, rendering, number, model) for number in numbers]
    prompts: list[str] = []

    def answer(**kwargs: Any) -> MagicMock:
        prompt = kwargs["contents"] if provider == "gemini" else kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        match = re.search(r'<call number="(\d+)"', prompt)
        assert match is not None
        number = int(match.group(1))
        if number == 3:
            raise connection_reset
        return reply("fail" if number in (1, 2, 4, 6) else "na" if number == 40 else "pass")

    client = MagicMock(spec=sdk)
    attrgetter(method)(client).side_effect = answer

    with patch.object(call_review, "RETRY_BACKOFF_SECONDS", 0):
        calls = judge_calibration.judge_all(client, requests, deadline=None)
    calibration = judge_calibration.calibrate(card, numbers, [call.verdict if call else None for call in calls])

    # Every fail and the first 35 passes, each sent as the review rendered it, with the judge prompt.
    assert numbers == list(range(1, 41))
    assert sorted(set(prompts)) == sorted(rendering.calls[number].text for number in numbers)
    assert all(JUDGE_PROMPT in request.system for request in requests)
    assert calibration == Calibration(
        review_fails=5,
        caught=3,
        review_passes=35,
        judged_passes=35,
        false_alarms=1,
        unjudged=1,
        na_on_fails=0,
        na_on_passes=1,
    )
    assert judge_calibration.keeps(card, calibration)
    # The false alarm and the na in 35 judged passes each stand for 45 / 35 of the review's 45 passes, so the judge
    # fails 3 + 1.3 calls, rounded to 4, of the 50 - 1.3 it would grade.
    measured = judge_calibration.measured(card, calibration)
    assert (measured.failed, measured.of) == (4, 49)
    # The reset call used every attempt and counts at its most, since a reset may have billed.
    price = MODEL_PRICES[model]
    served = 1000 * price.input_per_token + 50 * price.output_per_token
    assert len(prompts) == 39 + call_review.ATTEMPTS
    assert sum(call.cost_usd for call in calls if call) == pytest.approx(
        39 * served + judge_calibration.max_cost_usd([requests[2]])
    )


@parameterized.expand(
    [
        ("gemini_server_error", "gemini", genai_errors.ServerError(503, {}), True, True),
        ("gemini_rate_limited", "gemini", genai_errors.ClientError(429, {}), True, False),
        ("gemini_cancelled", "gemini", genai_errors.ClientError(499, {}), True, True),
        ("gemini_bad_request", "gemini", genai_errors.ClientError(400, {}), False, True),
        (
            "anthropic_overloaded",
            "anthropic",
            anthropic.APIStatusError("busy", response=httpx.Response(529, request=REQUEST), body=None),
            True,
            True,
        ),
    ]
)
def test_a_judge_call_retries_only_errors_a_retry_can_get_past(
    _name: str, provider: str, error: Exception, retried: bool, billed: bool
) -> None:
    card, rendering = _card_and_rendering()
    model = DEFAULT_MODEL_BY_PROVIDER[provider]
    request = judge_calibration.judge_request(card, rendering, 1, model)
    if provider == "gemini":
        client = MagicMock(spec=genai.Client)
        client.models.generate_content.side_effect = [error, _gemini_reply("fail")]
    else:
        client = MagicMock(spec=anthropic.Anthropic)
        client.messages.create.side_effect = [error, _anthropic_reply("fail")]

    with patch.object(call_review, "RETRY_BACKOFF_SECONDS", 0):
        call = judge_calibration.judge(client, request)

    price = MODEL_PRICES[model]
    served = 1000 * price.input_per_token + 50 * price.output_per_token
    unsettled = judge_calibration.max_cost_usd([request]) / call_review.ATTEMPTS if billed else 0.0
    assert call.verdict == ("fail" if retried else None)
    assert call.cost_usd == pytest.approx((served if retried else 0.0) + unsettled)


def test_a_request_that_could_end_past_the_deadline_never_starts() -> None:
    card, rendering = _card_and_rendering()
    client = MagicMock(spec=anthropic.Anthropic)

    calls = judge_calibration.judge_all(
        client, [judge_calibration.judge_request(card, rendering, 1, "claude-haiku-4-5")], deadline=time.monotonic()
    )

    assert calls == [None]
    client.messages.create.assert_not_called()
