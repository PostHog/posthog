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

from posthog.temporal.ai_observability.evaluation_llm_judge import ExecuteLLMJudgeInputs, run_generation_llm_judge

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
        ("fails_and_passes_share_the_slots", 40, 30, 0, (20, 20, 0)),
        ("few_fails_leave_their_slots_to_passes", 5, 45, 0, (5, 35, 0)),
        ("few_passes_leave_their_slots_to_fails", 45, 3, 0, (37, 3, 0)),
        ("passes_and_skipped_calls_share_the_pass_slots", 10, 5, 40, (10, 3, 27)),
    ]
)
def test_calibration_keeps_room_for_the_review_passes(
    _name: str, fails: int, passes: int, na: int, picked: tuple[int, int, int]
) -> None:
    # The skipped calls come before the passes, so an order-based pick would test no pass at all.
    verdicts = ["fail"] * fails + ["na"] * na + ["pass"] * passes
    labels = dict(enumerate(verdicts, start=1))
    card = MagicMock(labels=labels)

    numbers = judge_calibration.calibration_calls(card)

    assert tuple(sum(1 for n in numbers if labels[n] == kind) for kind in ("fail", "pass", "na")) == picked


@parameterized.expand(
    [
        ("answers_na_where_it_does_not_apply", "pass", "na", True, (5, 15)),
        ("fails_calls_it_does_not_apply_to", "pass", "fail", False, (35, 45)),
        ("fails_every_call_it_applies_to", "fail", "na", False, (15, 15)),
    ]
)
def test_a_judge_is_tested_on_passes_and_on_calls_the_question_skips(
    _name: str, on_pass: Verdict, on_na: Verdict, kept: bool, counts: tuple[int, int]
) -> None:
    labels: dict[int, Verdict] = {n: "fail" if n <= 5 else "na" if n <= 35 else "pass" for n in range(1, 46)}
    card = replace(_card_and_rendering()[0], labels=labels, failed=5, of=15)
    numbers = judge_calibration.calibration_calls(card)
    verdicts: dict[Verdict, Verdict] = {"fail": "fail", "pass": on_pass, "na": on_na}

    calibration = judge_calibration.calibrate(card, numbers, [verdicts[labels[n]] for n in numbers])

    assert judge_calibration.keeps(card, calibration) is kept
    measured = judge_calibration.measured(card, calibration)
    assert (measured.failed, measured.of) == counts


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
                    "summary": "Flags replies that promise a refund date",
                    "rule": "A reply fails when it names a date or day by which the refund arrives.",
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
                id="toolu_1", name="record_verdict", input={"reasoning": "r", "outcome": verdict}, type="tool_use"
            )
        ],
        usage=Usage(input_tokens=1000, output_tokens=50),
    )


def _openai_reply(verdict: str) -> MagicMock:
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({"reasoning": "r", "outcome": verdict})))],
        usage=MagicMock(prompt_tokens=1000, completion_tokens=50),
    )


def _gemini_reply(verdict: str) -> MagicMock:
    return MagicMock(
        text=json.dumps({"reasoning": "r", "outcome": verdict}),
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
        match = re.search(r"Output: Reply (\d+)$", prompt)
        assert match is not None
        number = int(match.group(1)) + 1
        if number == 3:
            raise connection_reset
        return reply("fail" if number in (1, 2, 4, 6) else "not_applicable" if number == 40 else "pass")

    client = MagicMock(spec=sdk)
    attrgetter(method)(client).side_effect = answer

    with patch.object(call_review, "RETRY_BACKOFF_SECONDS", 0):
        calls = judge_calibration.judge_all(client, requests, deadline=None)
    calibration = judge_calibration.calibrate(card, numbers, [call.verdict if call else None for call in calls])

    # Every fail and the first 35 passes, each sent once, and the reset call once more.
    assert numbers == list(range(1, 41))
    assert sorted(set(prompts)) == sorted(request.prompt for request in requests)
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
        ("anthropic", call_review, "build_ai_gateway_anthropic_client"),
        ("openai", judge_calibration, "build_openai_client"),
        ("gemini", judge_calibration, "build_gemini_client"),
    ]
)
def test_every_judge_client_tags_its_calls_with_the_run_trigger(provider: str, module: Any, builder: str) -> None:
    with patch.object(module, builder) as build:
        judge_calibration.build_client(7, "run-1", DEFAULT_MODEL_BY_PROVIDER[provider], "manual")

    assert build.call_args.kwargs["properties"]["trigger"] == "manual"


def test_a_judge_is_calibrated_on_the_prompts_the_accepted_evaluation_sends() -> None:
    tools = [{"type": "function", "function": {"name": "refund_status", "description": "Looks up a refund."}}]
    messages = [
        {"role": "system", "content": "Never promise a date."},
        {"role": "user", "content": "Where is my refund?"},
        {"role": "assistant", "content": "Let me check.", "tool_calls": [{"function": {"name": "refund_status"}}]},
    ]
    output = [{"role": "assistant", "content": "It arrives on Friday."}]
    row = ReviewCallRow(
        event_uuid="e1",
        trace_id="t1",
        call_type=SUPPORT.key,
        input=json.dumps(messages),
        output=json.dumps(output),
        tools=json.dumps(tools),
    )
    rendering = call_review.render([SUPPORT], call_review.select_calls([row]))
    card = replace(_card_and_rendering()[0], labels={1: "fail"})
    evaluation = {
        "id": "eval",
        "team_id": 1,
        "evaluation_type": "llm_judge",
        "evaluation_config": {"prompt": JUDGE_PROMPT, "include_media": False},
        "output_type": "boolean",
        "output_config": {"allows_na": True},
    }
    event = {
        "event": "$ai_generation",
        "properties": {"$ai_input": messages, "$ai_output_choices": output, "$ai_tools": tools},
    }

    with patch("posthog.temporal.ai_observability.evaluation_llm_judge.call_llm_judge") as runtime_judge:
        run_generation_llm_judge(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event))
    request = judge_calibration.judge_request(card, rendering, 1, DEFAULT_MODEL_BY_PROVIDER["openai"])

    sent = runtime_judge.call_args.kwargs
    assert (request.system, request.prompt) == (sent["system_prompt"], sent["user_prompt"])
    assert "refund_status" in request.prompt


@parameterized.expand(
    [
        ("numeric_output", json.dumps([{"role": "user", "content": "Count"}]), "42", "", "Output: 42"),
        ("null_input", "null", json.dumps("Done"), "", "Input: null"),
        (
            "cut_tool_catalog",
            json.dumps("Hi"),
            json.dumps("Hello"),
            '[{"type": "function", "function": {"na',
            "Input: Hi",
        ),
    ]
)
def test_a_judge_request_reads_any_stored_call(_name: str, input: str, output: str, tools: str, expected: str) -> None:
    row = ReviewCallRow(event_uuid="e1", trace_id="t1", call_type=SUPPORT.key, input=input, output=output, tools=tools)
    rendering = call_review.Rendering(
        text="",
        call_types={},
        trace_ids={},
        calls={1: call_review.RenderedCall(call_type=SUPPORT.key, row=row)},
        earlier_cards={},
    )

    request = judge_calibration.judge_request(
        _card_and_rendering()[0], rendering, 1, DEFAULT_MODEL_BY_PROVIDER["openai"]
    )

    assert expected in request.prompt
    assert "Tools available" not in request.prompt


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


@parameterized.expand(
    [
        ("gives_the_review_labels", "return not match(output, '^Reply [0-4]$')", True, (5, 50)),
        (
            "loops",
            "for (let reply in ['Reply 0', 'Reply 1', 'Reply 2', 'Reply 3', 'Reply 4']) {\n"
            "  if (output == reply) {\n    return false\n  }\n}\nreturn true",
            True,
            (5, 50),
        ),
        # Five of the review's passes are not JSON, so jsonParse raises on them, and each error counts against the code.
        (
            "raises_on_some_passes",
            "if (match(output, '^Reply [0-4]$')) {\n  return false\n}\n"
            "if (match(output, '^Reply [5-9]$')) {\n  return jsonParse(output).ok\n}\nreturn true",
            False,
            (5, 45),
        ),
        ("does_not_compile", "return match(output, 'Reply \\d')", None, None),
        ("multiplies", "let pad := ' ' * 2\nreturn not match(output, '^Reply [0-4]$')", None, None),
        ("formats_a_string", "let pad := '%5s' % output\nreturn not match(output, '^Reply [0-4]$')", None, None),
        ("calls_another_function", "return not match(replaceAll(output, 'x', 'y'), '^Reply [0-4]$')", None, None),
        # Data could hold a forged function, so no variable may take an allowed function's name.
        (
            "binds_an_allowed_name",
            "let parsed := {'f': lower}\nlet trim := parsed.f\nreturn not match(trim(output), '^Reply [0-4]$')",
            None,
            None,
        ),
        (
            "declares_an_allowed_name",
            "fun trim(text) {\n  return text\n}\nreturn not match(trim(output), '^Reply [0-4]$')",
            None,
            None,
        ),
        (
            "catches_into_an_allowed_name",
            "try {\n  throw {'__hogError__': true, 'type': 'Error', 'message': 'x'}\n} catch (trim) {\n"
            "  return not match(output, '^Reply [0-4]$')\n}\nreturn true",
            None,
            None,
        ),
        (
            "renames_another_function",
            "let lower := replaceAll\nreturn not match(lower(output, 'x', 'y'), '^Reply [0-4]$')",
            None,
            None,
        ),
        # A non-boolean result disables a saved Hog evaluation, so one such call rejects the check.
        (
            "returns_a_string_on_one_call",
            "if (output == 'Reply 49') {\n  return 'unsure'\n}\nreturn not match(output, '^Reply [0-4]$')",
            None,
            None,
        ),
    ]
)
def test_a_code_check_is_kept_only_when_it_gives_the_review_labels(
    _name: str, code_check: str, kept: bool | None, counts: tuple[int, int] | None
) -> None:
    card, rendering = _card_and_rendering()

    code = judge_calibration.check_code(replace(card, code_check=code_check), rendering, deadline=None)

    if kept is None:
        assert code is None
        return
    assert code is not None
    assert judge_calibration.keeps(card, code.calibration) is kept
    assert (code.failed, code.of) == counts


def test_a_kept_code_check_counts_its_rate_on_the_day_beyond_the_calls_the_review_read() -> None:
    card, rendering = _card_and_rendering()
    card = replace(card, code_check="return not match(output, '^Reply [0-4]$')")
    read = next(iter(rendering.calls.values())).row

    def call(uuid: str, call_type: str, reply: str) -> ReviewCallRow:
        return ReviewCallRow(
            event_uuid=uuid, trace_id=uuid, call_type=call_type, input=read.input, output=json.dumps(reply)
        )

    day = [
        read,
        call("d1", SUPPORT.key, "Reply 1"),
        call("d2", SUPPORT.key, "Reply 9"),
        call("d3", "prompt_name:other", "Reply 2"),
    ]
    code = judge_calibration.check_code(card, rendering, deadline=None)
    assert code is not None

    widened = judge_calibration.counted_on_day(card, code, rendering, day, deadline=None)
    out_of_time = judge_calibration.counted_on_day(card, code, rendering, day, deadline=time.monotonic())

    assert widened is not None and (widened.failed, widened.of) == (code.failed + 1, code.of + 2)
    assert widened.calibration == code.calibration
    assert out_of_time == code


def test_a_code_check_never_starts_a_call_that_could_run_past_the_deadline() -> None:
    card, rendering = _card_and_rendering()
    card = replace(card, code_check="return true")

    assert judge_calibration.check_code(card, rendering, deadline=time.monotonic() + 5) is None


def test_the_vm_refuses_functions_outside_the_set_when_the_source_check_misses_one() -> None:
    card, rendering = _card_and_rendering()
    card = replace(card, code_check="return not match(replaceAll(output, 'x', 'y'), '^Reply [0-4]$')")

    with patch.object(judge_calibration._OutsideCodeCheckSet, "visit"):
        assert judge_calibration.check_code(card, rendering, deadline=None) is None
