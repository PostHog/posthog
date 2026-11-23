import re
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, patch

from django.utils import timezone

import httpx
import openai
from anthropic import APIConnectionError
from anthropic.types import TextBlock, Usage
from parameterized import parameterized

from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions import call_review, pipeline, runs
from products.ai_observability.backend.logic.eval_suggestions.call_review import REVIEW_TEMPLATE_KEY
from products.ai_observability.backend.logic.eval_suggestions.call_review_queries import CallTypeRow, SnippetMatches
from products.ai_observability.backend.logic.eval_suggestions.config import SuggestionSettings
from products.ai_observability.backend.logic.eval_suggestions.coverage import (
    Coverage,
    ExistingEval,
    earlier_review_cards,
)
from products.ai_observability.backend.logic.eval_suggestions.eligibility import set_suggestions_turned_off
from products.ai_observability.backend.logic.eval_suggestions.measure import SampleRef
from products.ai_observability.backend.logic.eval_suggestions.pipeline import (
    dedupe,
    draft_stage,
    measure_stage,
    paid_call,
    publish_stage,
    screen_stage,
)
from products.ai_observability.backend.logic.eval_suggestions.prices import MODEL_PRICES
from products.ai_observability.backend.logic.eval_suggestions.ranking import Proposal
from products.ai_observability.backend.logic.eval_suggestions.runs import create_run, fail_run, publish
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)
from products.ai_observability.backend.models.evaluations import Evaluation

ALL_TRAFFIC = [{"id": "all", "rollout_percentage": 100, "properties": []}]
SECURITY_LENS = {"key": "review_lens", "value": ["security-1", "security-2"], "operator": "exact", "type": "event"}
GAP_PROMPT = "Decide whether every finding marked P0 or P1 deserves that level."


def _event(team: Team, event: str, at: datetime, properties: dict[str, Any]) -> None:
    """Heavy properties go to `ai_events` only, as ingestion does."""
    event_uuid = str(uuid.uuid4())
    light = {key: value for key, value in properties.items() if key not in HEAVY_PROPERTY_NAMES}
    _create_event(team=team, event=event, distinct_id="user-1", timestamp=at, properties=light, event_uuid=event_uuid)
    bulk_create_ai_events(
        [
            {
                "event": event,
                "event_uuid": event_uuid,
                "distinct_id": "user-1",
                "team_id": team.pk,
                "timestamp": at,
                "properties": properties,
            }
        ]
    )


def _content(captured: bool, messages: list[dict[str, Any]], choices: list[dict[str, Any]]) -> dict[str, Any]:
    """The input and output of a generation, or nothing, as an SDK in privacy mode sends it."""
    return {"$ai_input": messages, "$ai_output_choices": choices} if captured else {}


def _chat_traffic(team: Team, end: datetime, *, capture_content: bool = True, final_answer: bool = True) -> None:
    """60 chat turns over three days. Every action goes through one dispatcher tool, answers link to docs,
    some turns pause for approval, and 5 turns end on a timeout nobody retried."""
    for index in range(60):
        at = end - timedelta(hours=1 + index * 1.1)
        trace = {"$ai_trace_id": f"turn-{index}", "ai_product": "chat_assistant"}
        model = {"$ai_model": "gpt-5-mini"}
        messages: list[dict[str, Any]] = [{"role": "user", "content": "Move my meeting notes to the archive."}]
        for step in range(3):
            call = {
                "type": "function",
                "id": f"call-{index}-{step}",
                "function": {"name": "run_action", "arguments": json.dumps({"action": "list_notes"})},
            }
            assistant = {"role": "assistant", "content": "", "tool_calls": [call]}
            _event(
                team,
                "$ai_generation",
                at,
                {
                    **trace,
                    **model,
                    **_content(capture_content, messages, [assistant]),
                    "$ai_tools_called": "run_action",
                    "$ai_tool_call_count": 1,
                },
            )
            at += timedelta(seconds=2)
            _event(team, "$ai_span", at, {**trace, "$ai_span_name": "run_action"})
            messages = [*messages, assistant, {"role": "tool", "tool_call_id": call["id"], "content": "ok"}]
        # The last action's own span, or the approval pause, comes after the earlier spans, never at the same instant.
        at += timedelta(seconds=1)
        if index % 12 == 7:
            _event(
                team,
                "$ai_span",
                at,
                {
                    **trace,
                    "$ai_span_name": "run_action",
                    "$ai_is_error": True,
                    "$ai_error": "TimeoutError: action took longer than 30s",
                },
            )
        elif index % 10 == 3:
            _event(
                team,
                "$ai_span",
                at,
                {
                    **trace,
                    "$ai_span_name": "approval_gate",
                    "$ai_is_error": True,
                    "$ai_error": "GraphInterrupt(value={'needs_approval': 'archive'})",
                },
            )
        if not final_answer:
            continue
        answer = {
            "role": "assistant",
            "content": "Done. See https://example.com/docs/archive for version 2.1 of the archive.",
        }
        _event(
            team,
            "$ai_generation",
            at + timedelta(seconds=1),
            {**trace, **model, **_content(capture_content, messages, [answer])},
        )


def _dead_judge(team: Team) -> Evaluation:
    """An enabled judge whose filter names `chat`, a value the traffic no longer sends."""
    evaluation = Evaluation.objects.create(
        team=team,
        name="Chat answers are grounded",
        evaluation_type="llm_judge",
        evaluation_config={"prompt": "Return true when the answer is grounded in the tool results."},
        output_type="boolean",
        output_config={},
        target="trace",
        enabled=True,
        conditions=[
            {
                "id": "chat",
                "rollout_percentage": 100,
                "properties": [{"key": "ai_product", "value": ["chat"], "operator": "exact", "type": "event"}],
            }
        ],
    )
    Evaluation.objects.filter(pk=evaluation.pk).update(
        created_at=timezone.now() - timedelta(days=40), updated_at=timezone.now() - timedelta(days=10)
    )
    return evaluation


SUPPORT_PROMPT = "You answer refund questions for Example Shop. Never promise a refund date."
JUDGE_PROMPT = "Does the reply avoid promising a refund date? Pass when it gives no date, fail when it promises one."


def _support_traffic(
    team: Team, end: datetime, *, prompt_name: str | None = "support-reply", promises: int = 30
) -> None:
    """30 support replies over the last hours, each in its own trace, all from one prompt, and the first `promises`
    of them promise a refund date. An unnamed prompt is grouped by the start of its input, so it runs past that start
    for the calls to share one call type."""
    system = SUPPORT_PROMPT if prompt_name else SUPPORT_PROMPT + " See the policy." * 100
    for index in range(30):
        _event(
            team,
            "$ai_generation",
            end - timedelta(hours=1, minutes=index * 10),
            {
                "$ai_trace_id": f"support-{index}",
                "$ai_model": "gpt-5-mini",
                **({"$ai_prompt_name": prompt_name} if prompt_name else {}),
                "$ai_input": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Where is my refund for order {index}?"},
                ],
                "$ai_output_choices": [
                    {
                        "role": "assistant",
                        "content": "Your refund arrives by Friday."
                        if index < promises
                        else "Your refund is on its way.",
                    }
                ],
            },
        )


REVIEW_TITLE = "Replies promise refund dates"
# The generation's stored output is an assistant message list, so this passes only when the code reads its text.
AGREEING_CODE = "return not match(output, '^Your refund arrives by')"


def _calibration_record(*, caught: int, false_alarms: int, kept: bool) -> dict[str, Any]:
    counts = {
        "review_fails": 6,
        "caught": caught,
        "review_passes": 24,
        "judged_passes": 24,
        "false_alarms": false_alarms,
        "unjudged": 0,
        "na_on_fails": 0,
        "na_on_passes": 0,
    }
    return {"status": "ok", "model": "gpt-5-mini", "cards": [{"title": REVIEW_TITLE, **counts, "kept": kept}]}


def _review_replies(card: dict[str, Any]) -> Callable[..., MagicMock]:
    """The triage picks the support prompt. The review drafts `card` and labels each call it read by whether the
    reply promises a date."""

    def reply(**kwargs: Any) -> MagicMock:
        if kwargs["model"] == call_review.TRIAGE_MODEL:
            return _json_reply({"exclude": False, "picked": [{"id": "T1", "why": "answers users"}]})
        calls = re.findall(r'<call number="(\d+)"(.*?)</call>', kwargs["messages"][0]["content"], flags=re.DOTALL)
        labels = [{"call": int(n), "verdict": "fail" if "by Friday" in body else "pass"} for n, body in calls]
        return _json_reply({"product": "a shop", "themes": [], "cards": [{**card, "labels": labels}]})

    return reply


def _judge_replies(judge_fails: set[int]) -> Callable[..., MagicMock]:
    """The judge fails the replies to the orders numbered `judge_fails`, which it reads in the call's input."""

    def reply(**kwargs: Any) -> MagicMock:
        order = re.search(r"order (\d+)\?", kwargs["messages"][-1]["content"])
        assert order is not None
        verdict = "fail" if int(order.group(1)) in judge_fails else "pass"
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"reasoning": "r", "outcome": verdict})))],
            usage=MagicMock(prompt_tokens=1000, completion_tokens=50),
        )

    return reply


def _json_reply(answer: dict[str, Any]) -> MagicMock:
    return MagicMock(
        content=[TextBlock(text=json.dumps(answer), type="text")],
        usage=Usage(input_tokens=1000, output_tokens=500),
        stop_reason="end_turn",
    )


def _run_stages(
    team: Team,
    run: EvalSuggestionRun,
    *,
    include_paid: bool = False,
    now: datetime | None = None,
    settings: SuggestionSettings | None = None,
) -> list[EvalSuggestion]:
    """Every stage in order, as the team workflow runs them."""
    team_id, run_id, settings = team.pk, str(run.id), settings or SuggestionSettings()
    measure_stage(team_id, run_id, settings=settings, now=now)
    screen_stage(team_id, run_id, include_paid=include_paid, settings=settings)
    draft_stage(team_id, run_id, include_paid=include_paid, settings=settings)
    publish_stage(team_id, run_id)
    return list(EvalSuggestion.objects.for_team(team_id).filter(run=run))


@pytest.fixture(autouse=True)
def _organization_in_rollout() -> Any:
    with patch(
        "products.ai_observability.backend.logic.eval_suggestions.pipeline.runs_for_organization",
        return_value=True,
    ):
        yield


class TestPipeline(ClickhouseTestMixin, APIBaseTest):
    def test_finds_the_real_failures_and_none_of_the_noise(self) -> None:
        now = timezone.now()
        _chat_traffic(self.team, now - timedelta(minutes=30))
        dead_judge = _dead_judge(self.team)
        run = create_run(self.team, "manual")

        suggestions = {s.dedupe_key: s for s in _run_stages(self.team, run, now=now)}

        fix_key = f"fix:{dead_judge.id}:no_runs"
        assert set(suggestions) == {fix_key, "check:unrecovered_errors"}

        fix = suggestions[fix_key]
        assert fix.draft["conditions"][0]["properties"][0]["value"] == ["chat_assistant"]
        assert (fix.headline, fix.target_evaluation_id) == (
            "A filter value no longer appears in your events",
            dead_judge.id,
        )

        errors = suggestions["check:unrecovered_errors"]
        assert errors.measured_failure_rate is not None and 0 < errors.measured_failure_rate < 0.1
        assert errors.headline == "Tool or model calls that never succeed"
        # The observation and the stored rate come from the same counts.
        observed = re.fullmatch(r"(\d+) of (\d+) sampled traces flagged", errors.draft["observation"])
        assert observed is not None
        assert int(observed[1]) / int(observed[2]) == errors.measured_failure_rate
        assert int(observed[2]) == errors.sample_size
        assert all("GraphInterrupt" not in e["reason"] for e in errors.evidence)

        # The noise: dispatcher calls counted as loops.
        run.refresh_from_db()
        measured = run.stages["measure"]["checks"]
        assert measured["repeated_tool_calls"]["failed"] == 0
        # Paid stages were off, and the handoff is gone once the run published.
        assert run.stages["screening"] == {"status": "skipped", "detail": "free stages only"}
        assert run.handoff == {}

    def test_a_team_that_captures_no_content_gets_only_fix_cards(self) -> None:
        now = timezone.now()
        _chat_traffic(self.team, now - timedelta(minutes=30), capture_content=False)
        dead_judge = _dead_judge(self.team)
        run = create_run(self.team, "manual")

        suggestions = _run_stages(self.team, run, include_paid=True, now=now)

        assert [s.dedupe_key for s in suggestions] == [f"fix:{dead_judge.id}:no_runs"]
        run.refresh_from_db()
        assert run.stages["applicability"]["status"] == "skipped"

    @parameterized.expand(
        [
            # The judge catches 5 of the review's 6 fails and flags 2 of its 24 passes.
            ("judge_agrees", {0, 1, 2, 3, 4, 6, 7}, None, _calibration_record(caught=5, false_alarms=2, kept=True)),
            ("judge_misses_half", {0, 1, 2}, None, _calibration_record(caught=3, false_alarms=0, kept=False)),
            ("over_budget", {0, 1, 2, 3, 4, 6}, 10**7, {"status": "skipped", "detail": "budget used up"}),
            # The prompt has no name, so the card selects its generations by the prompt's text.
            (
                "judge_agrees_on_an_unnamed_prompt",
                {0, 1, 2, 3, 4, 6, 7},
                None,
                _calibration_record(caught=5, false_alarms=2, kept=True),
                None,
            ),
            # 26 of 30 calls break the rule, so the card asks for a prompt fix and no judge runs.
            (
                "most_calls_break_the_rule",
                set(),
                None,
                {"status": "skipped", "detail": "no cards"},
                "support-reply",
                26,
            ),
            (
                "code_check_agrees",
                set(),
                None,
                {"status": "skipped", "detail": "no cards"},
                "support-reply",
                6,
                AGREEING_CODE,
            ),
            (
                "code_check_does_not_compile",
                {0, 1, 2, 3, 4, 6, 7},
                None,
                _calibration_record(caught=5, false_alarms=2, kept=True),
                "support-reply",
                6,
                "return match(output, 'by \\d')",
            ),
        ]
    )
    def test_a_reviewed_judge_publishes_only_when_the_team_model_agrees(
        self,
        _name: str,
        judge_fails: set[int],
        max_output_tokens: int | None,
        record: dict[str, Any],
        prompt_name: str | None = "support-reply",
        review_fails: int = 6,
        code_check: str = "",
    ) -> None:
        now = timezone.now()
        _support_traffic(self.team, now - timedelta(minutes=30), prompt_name=prompt_name, promises=review_fails)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        run = create_run(self.team, "manual")
        examples = [
            {"trace_id": "support-3", "what_went_wrong": "Promised the refund by Friday"},
            {"trace_id": "support-7", "what_went_wrong": "Promised the refund by Friday"},
        ]
        card = {
            "title": REVIEW_TITLE,
            "summary": "Flags replies that promise a refund date",
            "rule": "A reply fails when it names a date or day by which the refund arrives.",
            "why": "The prompt says never to promise a refund date",
            "call_types": ["T1"],
            "examples": examples,
            "judge_prompt": JUDGE_PROMPT,
            "code_check": code_check,
        }
        client = MagicMock()
        client.messages.create.side_effect = _review_replies(card)
        judge = MagicMock(spec=openai.OpenAI)
        judge.chat.completions.create.side_effect = _judge_replies(judge_fails)

        with (
            patch.object(pipeline.call_review, "build_client", return_value=client),
            patch.object(pipeline.judge_calibration, "build_client", return_value=judge),
            patch.object(
                pipeline.judge_calibration,
                "MAX_OUTPUT_TOKENS",
                max_output_tokens or pipeline.judge_calibration.MAX_OUTPUT_TOKENS,
            ),
            patch.object(runs, "is_enabled_for_organization", return_value=False),
            patch.object(runs, "report_team_action") as report,
        ):
            suggestions = _run_stages(
                self.team,
                run,
                include_paid=True,
                now=now,
                settings=SuggestionSettings(jeeves=False, llm_drafting=True),
            )

        run.refresh_from_db()
        assert run.stages["drafting"]["status"] == "ok"
        assert run.stages["drafting"]["calibration"] == record
        assert run.cost_usd > 0
        kept = int(record["status"] == "ok" and record["cards"][0]["kept"])
        coded = code_check == AGREEING_CODE
        [(_team, event, properties)] = [c.args for c in report.call_args_list]
        assert event == runs.RUN_FINISHED_EVENT
        assert {
            k: properties[k]
            for k in ("trigger", "status", "shadow", "calls_reviewed", "review_cards_drafted", "review_code_checks")
        } == {
            "trigger": "manual",
            "status": "completed",
            "shadow": True,
            "calls_reviewed": 30,
            "review_cards_drafted": 1,
            "review_code_checks": int(coded),
        }
        assert (properties["review_cards_kept"], properties["cards_published"]) == (kept, len(suggestions))
        assert properties["cost_usd"] == run.cost_usd
        prompt_fixes = [s for s in suggestions if s.kind == "fix_prompt"]
        assert [(s.headline, s.measured_failure_rate) for s in prompt_fixes] == (
            [(REVIEW_TITLE, review_fails / 30)] if review_fails > 6 else []
        )
        assert run.stages["drafting"]["prompt_bugs"] == len(prompt_fixes)
        if prompt_fixes:
            assert judge.chat.completions.create.call_count == 0
        assert [(c["compiles"], c["kept"]) for c in run.stages["drafting"]["code_calibration"]] == (
            [(coded, coded)] if code_check else []
        )
        code_cards = [s for s in suggestions if s.kind == "new_hog" and s.template_key == "review"]
        if coded:
            [code_card] = code_cards
            assert judge.chat.completions.create.call_count == 0
            assert code_card.draft["evaluation_config"] == {"source": call_review.code_check_source(code_check)}
            assert (code_card.draft["evaluation_type"], code_card.draft["target"]) == ("hog", "generation")
            assert code_card.filters == [
                {"key": "$ai_prompt_name", "value": ["support-reply"], "operator": "exact", "type": "event"}
            ]
            assert (code_card.headline, code_card.measured_failure_rate, code_card.sample_size) == (
                REVIEW_TITLE,
                6 / 30,
                30,
            )
            return
        assert code_cards == []
        reviewed = [s for s in suggestions if s.kind == "new_llm_judge" and s.template_key == "review"]
        if not (record["status"] == "ok" and record["cards"][0]["kept"]):
            assert reviewed == []
            return
        [suggestion] = reviewed
        assert suggestion.draft["evaluation_config"] == {"prompt": JUDGE_PROMPT}
        assert suggestion.draft["target"] == "generation"
        assert suggestion.draft["calibration"] == {
            k: v for k, v in record["cards"][0].items() if k not in ("title", "kept")
        }
        assert suggestion.filters == (
            [{"key": "$ai_prompt_name", "value": ["support-reply"], "operator": "exact", "type": "event"}]
            if prompt_name
            else [
                {
                    "key": "$ai_input",
                    "value": "You answer refund questions for Example Shop",
                    "operator": "icontains",
                    "type": "event",
                }
            ]
        )
        assert suggestion.evidence == [{"trace_id": e["trace_id"], "reason": e["what_went_wrong"]} for e in examples]
        # The judge's own fails, 5 caught and 2 false alarms, not the review's 6.
        assert (suggestion.headline, suggestion.measured_failure_rate, suggestion.sample_size) == (
            REVIEW_TITLE,
            7 / 30,
            30,
        )
        # The review read every sampled call, with the call type's system prompt shown once, and the judge read each.
        review_prompt = client.messages.create.call_args_list[1].kwargs["messages"][0]["content"]
        assert review_prompt.count(SUPPORT_PROMPT) == 1
        assert review_prompt.count("<call ") == 30
        assert judge.chat.completions.create.call_count == 30

    def test_an_agent_whose_turns_end_on_a_tool_call_is_not_gated(self) -> None:
        now = timezone.now()
        _chat_traffic(self.team, now - timedelta(minutes=30), final_answer=False)
        run = create_run(self.team, "manual")

        _run_stages(self.team, run, now=now)

        run.refresh_from_db()
        assert run.stages["profile"]["text_share"] == 0
        assert run.stages["applicability"]["status"] == "ok"


class TestRunRetries(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("publish_retried_after_its_result_was_lost", lambda run: publish_stage(run.team_id, str(run.id))),
            (
                "measure_attempt_that_outlived_the_run",
                lambda run: measure_stage(run.team_id, str(run.id), settings=SuggestionSettings()),
            ),
        ]
    )
    def test_a_late_attempt_keeps_the_published_cards(
        self, _name: str, late_attempt: Callable[[EvalSuggestionRun], object]
    ) -> None:
        dead_judge = _dead_judge(self.team)
        run = create_run(self.team, "scheduled")
        with patch.object(runs, "report_team_action") as report:
            _run_stages(self.team, run)
            late_attempt(run)

        assert report.call_count == 1

        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.COMPLETED
        assert list(
            EvalSuggestion.objects.for_team(self.team.pk).filter(run=run).values_list("dedupe_key", "status")
        ) == [(f"fix:{dead_judge.id}:no_runs", "proposed")]

    @parameterized.expand([("next_run_succeeds", False), ("next_run_fails", True)])
    def test_only_a_completed_run_replaces_the_previous_cards(self, _name: str, next_run_fails: bool) -> None:
        _dead_judge(self.team)
        first = create_run(self.team, "scheduled")
        _run_stages(self.team, first)
        second = create_run(self.team, "scheduled")

        with patch.object(runs, "report_team_action") as report:
            if next_run_fails:
                with patch.object(pipeline, "fetch_profile", side_effect=RuntimeError("ClickHouse timed out")):
                    with pytest.raises(RuntimeError):
                        measure_stage(self.team.pk, str(second.id), settings=SuggestionSettings())
                # The workflow fails the run once the stage used up its attempts, and may fail it again on a retry.
                fail_run(self.team.pk, str(second.id), "RuntimeError: ClickHouse timed out")
                fail_run(self.team.pk, str(second.id), "RuntimeError: ClickHouse timed out")
            else:
                _run_stages(self.team, second)

        [(_team, _event, properties)] = [c.args for c in report.call_args_list]
        assert (properties["status"], properties["error_type"]) == (
            ("failed", "RuntimeError") if next_run_fails else ("completed", "")
        )

        statuses = dict(EvalSuggestion.objects.for_team(self.team.pk).values_list("run_id", "status"))
        second.refresh_from_db()
        assert second.status == (
            EvalSuggestionRunStatus.FAILED if next_run_fails else EvalSuggestionRunStatus.COMPLETED
        )
        assert statuses[first.id] == ("proposed" if next_run_fails else "expired")

    def test_a_stale_measure_attempt_cannot_overwrite_a_later_stage(self) -> None:
        _dead_judge(self.team)
        run = create_run(self.team, "scheduled")
        settings = SuggestionSettings()
        measure_stage(self.team.pk, str(run.id), settings=settings)
        screen_stage(self.team.pk, str(run.id), include_paid=False, settings=settings)
        run.refresh_from_db()
        screened = run.handoff

        # Attempt 1 of measure outlived its retry and finishes after screening wrote the handoff.
        measure_stage(self.team.pk, str(run.id), settings=settings)

        run.refresh_from_db()
        assert run.handoff == screened
        assert run.handoff["written_by"] == "screening"

    def test_a_stale_attempt_that_fails_leaves_the_newer_attempt_to_publish(self) -> None:
        dead_judge = _dead_judge(self.team)
        run = create_run(self.team, "scheduled")
        # Attempt 1 timed out in Temporal's view and attempt 2 measured. Attempt 1's thread then raises.
        measure_stage(self.team.pk, str(run.id), settings=SuggestionSettings())
        with patch.object(pipeline, "fetch_profile", side_effect=RuntimeError("ClickHouse timed out")):
            with pytest.raises(RuntimeError):
                measure_stage(self.team.pk, str(run.id), settings=SuggestionSettings())

        assert publish_stage(self.team.pk, str(run.id)) == 1
        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.COMPLETED
        assert [s.dedupe_key for s in EvalSuggestion.objects.for_team(self.team.pk).filter(run=run)] == [
            f"fix:{dead_judge.id}:no_runs"
        ]
        # Neither paid stage ran, so publish records them as unfinished.
        assert run.stages["drafting"] == {"status": "failed", "detail": "the stage did not finish"}


class TestReviewBudget(BaseTest):
    def test_spend_is_held_before_each_call_and_kept_when_the_call_fails(self) -> None:
        call_type = CallTypeRow(source="prompt_name", name="support", calls=100, model="gpt-5-mini", example_input="")
        request = call_review.triage_request([call_type])
        reserve = call_review.max_cost_usd(request)
        price = MODEL_PRICES[request.model]
        served_cost = 1000 * price.input_per_token + 500 * price.output_per_token
        # Room for one served call and one reservation, not for a second reservation on top.
        budget = served_cost + 1.5 * reserve
        served, failed, refused = (create_run(self.team, "scheduled", batch_id="batch-1") for _ in range(3))
        connection_reset = APIConnectionError(request=httpx.Request("POST", "https://gateway.example.com"))
        client = MagicMock()
        client.messages.create.side_effect = [
            _json_reply({"exclude": False, "picked": []}),
            *[connection_reset] * call_review.ATTEMPTS,
        ]

        with patch.object(call_review, "RETRY_BACKOFF_SECONDS", 0):
            call = paid_call(served, client, request, budget)
            with pytest.raises(APIConnectionError):
                paid_call(failed, client, request, budget)
            refused_call = paid_call(refused, client, request, budget)

        assert call is not None and call.answer == {"exclude": False, "picked": []}
        assert refused_call is None
        spent = dict(EvalSuggestionRun.objects.for_team(self.team.pk).values_list("id", "cost_usd"))
        assert spent[served.id] == pytest.approx(served_cost)
        assert spent[failed.id] == pytest.approx(reserve)
        assert spent[refused.id] == 0
        # The failed call used every attempt, and the refused one never reached the provider.
        assert client.messages.create.call_count == 1 + call_review.ATTEMPTS


class TestRunRecords(BaseTest):
    def test_a_retried_start_reuses_its_run(self) -> None:
        run_id = "0f2c6a5e-1d7b-5a3e-9c1f-2b8e4d6a7c90"
        first = create_run(self.team, "scheduled", run_id=run_id)
        second = create_run(self.team, "scheduled", run_id=run_id)

        assert str(first.id) == str(second.id) == run_id
        assert EvalSuggestionRun.objects.for_team(self.team.pk).count() == 1

    @parameterized.expand(
        [
            ("running_run_fails", EvalSuggestionRunStatus.RUNNING, EvalSuggestionRunStatus.FAILED),
            ("published_run_stays", EvalSuggestionRunStatus.COMPLETED, EvalSuggestionRunStatus.COMPLETED),
        ]
    )
    def test_exhausted_attempts_mark_the_run_failed_unless_it_published(
        self, _name: str, before: str, after: str
    ) -> None:
        run = create_run(self.team, "scheduled")
        EvalSuggestionRun.objects.for_team(self.team.pk).filter(id=run.id).update(status=before)

        fail_run(self.team.pk, str(run.id), "Activity task timed out")

        run.refresh_from_db()
        assert run.status == after

    def test_an_attempt_publishes_nothing_once_the_run_was_given_up(self) -> None:
        run = create_run(self.team, "scheduled")
        fail_run(self.team.pk, str(run.id), "Activity task timed out")

        assert publish(run, [_candidate("check:unrecovered_errors", [])], {}) == []
        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.FAILED
        assert not EvalSuggestion.objects.for_team(self.team.pk).exists()

    def test_a_card_dismissed_while_the_run_works_is_not_published_again(self) -> None:
        earlier = create_run(self.team, "scheduled")
        publish(earlier, [_candidate("check:unrecovered_errors", [])], {})
        card = EvalSuggestion.objects.for_team(self.team.pk).get(run=earlier)
        run = create_run(self.team, "scheduled")
        # The new run read the team's dismissals before this one.
        EvalSuggestion.objects.for_team(self.team.pk).filter(id=card.id).update(
            status=EvalSuggestionStatus.DISMISSED, decided_at=timezone.now()
        )

        assert publish(run, [_candidate("check:unrecovered_errors", [])], {}) == []

    def test_the_review_reads_the_latest_card_of_each_earlier_check(self) -> None:
        def reviewed(key: str, name: str) -> Proposal:
            return replace(
                _candidate(key, [], "Is it right?"),
                template_key=REVIEW_TEMPLATE_KEY,
                draft={"name": name, "description": f"Whether {name} holds"},
            )

        first = create_run(self.team, "scheduled")
        publish(first, [reviewed("review:a", "dates"), reviewed("review:b", "tone"), CHECK], {})
        # Suggested before the memory window, and dismissed within it.
        EvalSuggestion.objects.for_team(self.team.pk).filter(dedupe_key="review:b").update(
            status=EvalSuggestionStatus.DISMISSED,
            decided_at=timezone.now(),
            created_at=timezone.now() - timedelta(days=100),
        )
        publish(create_run(self.team, "scheduled"), [reviewed("review:a", "refund dates")], {})

        assert [(card.dedupe_key, card.status, card.title) for card in earlier_review_cards(self.team)] == [
            ("review:a", "proposed", "refund dates"),
            ("review:b", "dismissed", "tone"),
        ]

    def test_a_card_accepted_while_the_run_works_is_not_published_again(self) -> None:
        run = create_run(self.team, "scheduled")
        earlier = create_run(self.team, "scheduled")
        publish(earlier, [_candidate("check:unrecovered_errors", [])], {})
        EvalSuggestion.objects.for_team(self.team.pk).filter(run=earlier).update(
            status=EvalSuggestionStatus.ACCEPTED, decided_at=timezone.now()
        )

        assert publish(run, [_candidate("check:unrecovered_errors", [])], {}) == []

    @parameterized.expand([("organization_out_of_the_rollout", False, False), ("project_turned_off", True, True)])
    @patch.object(pipeline.coverage_stage, "fetch_coverage")
    def test_a_queued_run_that_may_no_longer_run_does_nothing(
        self, _name: str, in_rollout: bool, turned_off: bool, fetch_coverage: MagicMock
    ) -> None:
        run = create_run(self.team, "scheduled")
        set_suggestions_turned_off(self.team, turned_off)

        with patch.object(pipeline, "runs_for_organization", return_value=in_rollout):
            assert measure_stage(self.team.pk, str(run.id), settings=SuggestionSettings()) == 0

        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.FAILED
        fetch_coverage.assert_not_called()
        assert publish_stage(self.team.pk, str(run.id)) == 0

    @parameterized.expand(
        [
            ("free_stages_only", False, SuggestionSettings(llm_drafting=True), True, None, "free stages only"),
            ("switched_off", True, SuggestionSettings(), True, None, "switched off"),
            (
                "no_consent",
                True,
                SuggestionSettings(llm_drafting=True),
                False,
                None,
                "AI data processing not approved",
            ),
            ("too_late_to_finish", True, SuggestionSettings(llm_drafting=True), True, 0.0, "not enough time left"),
            (
                "judge_model_the_gateway_cannot_serve",
                True,
                SuggestionSettings(llm_drafting=True),
                True,
                None,
                "no gateway route to calibrate judges on unrouted-model",
                "unrouted-model",
            ),
            (
                "turned_off_while_the_run_works",
                True,
                SuggestionSettings(llm_drafting=True),
                True,
                None,
                "turned off by the project",
                "gpt-5-mini",
                True,
            ),
        ]
    )
    def test_the_review_runs_only_when_allowed_and_in_time(
        self,
        _name: str,
        include_paid: bool,
        settings: SuggestionSettings,
        consent: bool,
        deadline: float | None,
        detail: str,
        judge_model: str = "gpt-5-mini",
        turned_off: bool = False,
    ) -> None:
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save()
        set_suggestions_turned_off(self.team, turned_off)
        run = create_run(self.team, "scheduled")
        handoff = runs.Handoff(
            window=pipeline.ProfileWindow(start=timezone.now() - timedelta(days=7), end=timezone.now()),
            profile=pipeline.TeamProfile.empty(),
            sample=[SampleRef(trace_id="t1", days=1, held_out=False)],
            proposals=[],
            screened_judges=[],
            judge_target="trace",
            judge_model=judge_model,
            sources={},
            candidate_options={},
        )

        with (
            patch.object(runs, "load_handoff", return_value=handoff),
            patch.object(pipeline, "load_call_types") as load_call_types,
        ):
            drafted = draft_stage(
                self.team.pk, str(run.id), include_paid=include_paid, settings=settings, deadline=deadline
            )

        assert drafted == 0
        load_call_types.assert_not_called()
        run.refresh_from_db()
        assert run.stages["drafting"] == {"status": "skipped", "detail": detail}


def _existing(**overrides: Any) -> ExistingEval:
    fields: dict[str, Any] = {
        "id": "existing",
        "name": "Existing check",
        "evaluation_type": "hog",
        "enabled": True,
        "target": "trace",
        "conditions": ALL_TRAFFIC,
        "template_key": None,
        "dedupe_key": "check:unrecovered_errors",
        "source_hash": None,
        "prompt": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
        **overrides,
    }
    return ExistingEval(**fields)


def _candidate(dedupe_key: str, filters: list[dict[str, Any]], prompt: str | None = None) -> Proposal:
    return Proposal(
        kind="new_llm_judge" if prompt else "new_hog",
        template_key="structured_output_gap" if prompt else "unrecovered_errors",
        dedupe_key=dedupe_key,
        headline=dedupe_key,
        outcome="",
        reason="",
        draft={"target": "trace", "evaluation_config": {"prompt": prompt} if prompt else {"source": "return true"}},
        filters=filters,
        rollout_percentage=100,
        measured_failure_rate=None,
        sample_size=None,
        evidence=[],
        score=1.0,
    )


CHECK = _candidate("check:unrecovered_errors", [])
SECURITY_GAP = _candidate("gap:review_lens=security:findings[].priority", [SECURITY_LENS], GAP_PROMPT)
AUTH_GAP = _candidate(
    "gap:review_lens=auth:findings[].priority",
    [{"key": "review_lens", "value": ["auth"], "operator": "exact", "type": "event"}],
    GAP_PROMPT,
)


@parameterized.expand(
    [
        ("enabled_on_all_traffic_covers_it", _existing(), CHECK, False),
        (
            "a_sampled_rollout_still_covers_it",
            _existing(conditions=[{**ALL_TRAFFIC[0], "rollout_percentage": 5}]),
            CHECK,
            False,
        ),
        ("a_disabled_copy_does_not", _existing(enabled=False), CHECK, True),
        ("a_copy_on_another_unit_does_not", _existing(target="generation"), CHECK, True),
        (
            "a_copy_scoped_to_staging_does_not",
            _existing(conditions=[{**ALL_TRAFFIC[0], "properties": [{"key": "env", "value": ["staging"]}]}]),
            CHECK,
            True,
        ),
        (
            "a_wider_filter_covers_it",
            _existing(
                dedupe_key=AUTH_GAP.dedupe_key,
                conditions=[{**ALL_TRAFFIC[0], "properties": [{**SECURITY_LENS, "value": ["security-1", "auth"]}]}],
            ),
            AUTH_GAP,
            False,
        ),
        (
            "an_accepted_gap_judge_does_not_cover_another_segment",
            _existing(
                dedupe_key=SECURITY_GAP.dedupe_key,
                prompt=GAP_PROMPT,
                conditions=[{**ALL_TRAFFIC[0], "properties": [SECURITY_LENS]}],
            ),
            AUTH_GAP,
            True,
        ),
    ]
)
def test_dedupe_drops_a_candidate_only_where_an_evaluation_already_runs(
    _name: str, existing: ExistingEval, candidate: Proposal, kept: bool
) -> None:
    coverage = Coverage(evals=[existing], fixes=[], dismissed_dedupe_keys=frozenset())

    result = dedupe([candidate], coverage, {}, {})

    assert [(p.dedupe_key, p.similar_evaluation_id) for p in result] == (
        [(candidate.dedupe_key, existing.id)] if kept else []
    )


def test_a_less_confident_match_that_covers_the_scope_still_drops_the_candidate() -> None:
    narrow = _existing(id="narrow", conditions=[{**ALL_TRAFFIC[0], "properties": [SECURITY_LENS]}])
    wide = _existing(id="wide", conditions=ALL_TRAFFIC)
    coverage = Coverage(evals=[narrow, wide], fixes=[], dismissed_dedupe_keys=frozenset())

    assert dedupe([AUTH_GAP], coverage, {AUTH_GAP.dedupe_key: [(narrow, 0.95), (wide, 0.7)]}, {}) == []


@parameterized.expand(
    [
        ("count_runs", False, None, {"input:1": "You answer refund questions for Example Shop"}),
        ("count_fails", False, RuntimeError("Memory limit exceeded"), {}),
        # The snippet would reach members who may not read $ai_input through the accepted evaluation's conditions.
        ("team_has_property_access_rules", True, None, {}),
    ]
)
def test_an_unnamed_call_type_gets_a_prompt_text_filter_only_when_safe_to_count(
    _name: str, has_rules: bool, error: Exception | None, expected: dict[str, str]
) -> None:
    system = {"role": "system", "content": "You answer refund questions for Example Shop"}
    call_type = CallTypeRow(source="input", name="1", calls=10, model="m", example_input=json.dumps([system]))
    card = call_review.ReviewCard(
        title="Refund dates",
        summary="s",
        rule="r",
        why="w",
        call_types=[call_type],
        labels={},
        failed=3,
        of=10,
        examples=[],
        judge_prompt="j",
    )
    counts = {"1": [SnippetMatches(matched=10, in_call_type=10)] * 5}

    with (
        patch.object(pipeline, "team_has_property_access_rules", return_value=has_rules),
        patch.object(pipeline, "snippet_matches", return_value=counts, side_effect=error),
    ):
        snippets = pipeline._prompt_snippets(MagicMock(pk=1), MagicMock(), 1000, [call_type], [card], None)

    assert snippets == expected
