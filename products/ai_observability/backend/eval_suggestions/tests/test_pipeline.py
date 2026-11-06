import re
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Literal

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, patch

from django.utils import timezone

import httpx
from openai import APIConnectionError, RateLimitError
from parameterized import parameterized

from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.team import Team

from products.ai_observability.backend.eval_suggestions import drafting, pipeline
from products.ai_observability.backend.eval_suggestions.config import SuggestionSettings
from products.ai_observability.backend.eval_suggestions.coverage import Coverage, ExistingEval
from products.ai_observability.backend.eval_suggestions.pipeline import (
    create_run,
    dedupe,
    execute_run,
    fail_run,
    paid_draft,
    publish,
    run_pipeline,
)
from products.ai_observability.backend.eval_suggestions.ranking import Proposal
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
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


def _chat_traffic(team: Team, end: datetime) -> None:
    """60 chat turns over three days. Every action goes through one dispatcher tool, answers link to docs,
    some turns pause for approval, and 3 turns end on a timeout nobody retried."""
    for index in range(60):
        at = end - timedelta(hours=1 + index * 1.1)
        trace = {"$ai_trace_id": f"turn-{index}", "ai_product": "chat_assistant"}
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
                    "$ai_input": messages,
                    "$ai_output_choices": [assistant],
                    "$ai_tools_called": "run_action",
                    "$ai_tool_call_count": 1,
                },
            )
            at += timedelta(seconds=2)
            _event(team, "$ai_span", at, {**trace, "$ai_span_name": "run_action"})
            messages = [*messages, assistant, {"role": "tool", "tool_call_id": call["id"], "content": "ok"}]
        # The last action's own span, or the approval pause, comes after the earlier spans, never at the same instant.
        at += timedelta(seconds=1)
        if index % 20 == 7:
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
        answer = {
            "role": "assistant",
            "content": "Done. See https://example.com/docs/archive for version 2.1 of the archive.",
        }
        _event(
            team,
            "$ai_generation",
            at + timedelta(seconds=1),
            {**trace, "$ai_input": messages, "$ai_output_choices": [answer]},
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


class TestPipeline(ClickhouseTestMixin, APIBaseTest):
    def test_finds_the_real_failures_and_none_of_the_noise(self) -> None:
        now = timezone.now()
        _chat_traffic(self.team, now - timedelta(minutes=30))
        dead_judge = _dead_judge(self.team)
        run = create_run(self.team, "manual")

        suggestions = {
            s.dedupe_key: s
            for s in run_pipeline(self.team, run, include_paid=False, settings=SuggestionSettings(), now=now)
        }

        fix_key = f"fix:{dead_judge.id}:no_runs"
        assert set(suggestions) == {fix_key, "check:unrecovered_errors"}

        fix = suggestions[fix_key]
        assert fix.draft["conditions"][0]["properties"][0]["value"] == ["chat_assistant"]
        assert fix.headline == f'Your "{dead_judge.name}" eval stopped running'

        errors = suggestions["check:unrecovered_errors"]
        assert errors.measured_failure_rate is not None and 0 < errors.measured_failure_rate < 0.1
        assert re.fullmatch(r"1 in \d+ traces ends on a failed call", errors.headline)
        assert all("GraphInterrupt" not in e["reason"] for e in errors.evidence)

        # The noise: links counted as sensitive data, and dispatcher calls counted as loops.
        measured = EvalSuggestionRun.objects.for_team(self.team.pk).get(id=run.id).stages["measure"]["checks"]
        assert measured["sensitive_data"]["failed"] == 0
        assert measured["repeated_tool_calls"]["failed"] == 0


class TestRunRetries(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            (
                "retry_after_the_result_was_lost",
                lambda run: execute_run(str(run.id), include_paid=False, settings=SuggestionSettings()),
            ),
            (
                "attempt_racing_the_first_to_publish",
                lambda run: run_pipeline(run.team, run, include_paid=False, settings=SuggestionSettings()),
            ),
        ]
    )
    def test_a_second_attempt_keeps_the_published_cards(
        self, _name: str, second_attempt: Callable[[EvalSuggestionRun], object]
    ) -> None:
        dead_judge = _dead_judge(self.team)
        run = create_run(self.team, "scheduled")
        execute_run(str(run.id), include_paid=False, settings=SuggestionSettings())

        second_attempt(run)

        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.COMPLETED
        assert list(
            EvalSuggestion.objects.for_team(self.team.pk).filter(run=run).values_list("dedupe_key", "status")
        ) == [(f"fix:{dead_judge.id}:no_runs", "proposed")]

    @parameterized.expand([("next_run_succeeds", False), ("next_run_fails", True)])
    def test_only_a_completed_run_replaces_the_previous_cards(self, _name: str, next_run_fails: bool) -> None:
        _dead_judge(self.team)
        first = create_run(self.team, "scheduled")
        execute_run(str(first.id), include_paid=False, settings=SuggestionSettings())
        second = create_run(self.team, "scheduled")

        if next_run_fails:
            with patch(
                "products.ai_observability.backend.eval_suggestions.pipeline.fetch_profile",
                side_effect=RuntimeError("ClickHouse timed out"),
            ):
                with pytest.raises(RuntimeError):
                    execute_run(str(second.id), include_paid=False, settings=SuggestionSettings())
        else:
            execute_run(str(second.id), include_paid=False, settings=SuggestionSettings())

        statuses = dict(EvalSuggestion.objects.for_team(self.team.pk).values_list("run_id", "status"))
        second.refresh_from_db()
        assert second.status == (
            EvalSuggestionRunStatus.FAILED if next_run_fails else EvalSuggestionRunStatus.COMPLETED
        )
        assert statuses[first.id] == ("proposed" if next_run_fails else "expired")


def _completion(content: str) -> MagicMock:
    response = MagicMock(service_tier="flex")
    response.usage.prompt_tokens = 1000
    response.usage.completion_tokens = 500
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestDraftingBudget(BaseTest):
    def test_spend_is_held_before_each_call_and_kept_when_the_call_fails(self) -> None:
        brief = json.dumps({"field": "findings[].priority"})
        reserve = drafting.max_cost_usd(brief)
        served_cost = 1000 * drafting.INPUT_PRICE_PER_TOKEN + 500 * drafting.OUTPUT_PRICE_PER_TOKEN
        # Room for one served call and one reservation, not for a second reservation on top.
        budget = served_cost + 1.5 * reserve
        served, failed, refused = (create_run(self.team, "scheduled", batch_id="batch-1") for _ in range(3))
        connection_reset = APIConnectionError(request=httpx.Request("POST", "https://gateway.example.com"))
        client = MagicMock()
        client.with_options.return_value = client
        client.chat.completions.create.side_effect = [
            _completion(json.dumps({"evaluation_type": "hog", "name": "n", "description": "d", "body": "return true"})),
            *[connection_reset] * (2 + drafting.STANDARD_MAX_RETRIES),
        ]

        with (
            patch.object(drafting, "build_openai_client", return_value=client),
            patch.object(drafting, "RETRY_BACKOFF_SECONDS", 0),
        ):
            call = paid_draft(self.team, served, brief, budget)
            with pytest.raises(APIConnectionError):
                paid_draft(self.team, failed, brief, budget)
            refused_call = paid_draft(self.team, refused, brief, budget)

        assert call is not None and call.draft is not None
        assert refused_call is None
        spent = dict(EvalSuggestionRun.objects.for_team(self.team.pk).values_list("id", "cost_usd"))
        assert spent[served.id] == pytest.approx(served_cost)
        assert spent[failed.id] == pytest.approx(reserve)
        assert spent[refused.id] == 0
        # The failed call tried flex and every standard attempt, and the refused one never reached the provider.
        assert client.chat.completions.create.call_count == 3 + drafting.STANDARD_MAX_RETRIES

    @parameterized.expand(
        [
            ("lost_flex_response_may_have_billed", False, 0, 1),
            ("capacity_refusal_never_bills", True, 0, 0),
            ("lost_standard_retry_may_have_billed_too", False, 1, 2),
        ]
    )
    def test_a_failed_attempt_keeps_its_spend_unless_refused(
        self, _name: str, refused: bool, standard_failures: int, unsettled_calls: int
    ) -> None:
        brief = json.dumps({"field": "findings[].priority"})
        served_cost = 1000 * drafting.INPUT_PRICE_PER_TOKEN + 500 * drafting.OUTPUT_PRICE_PER_TOKEN
        request = httpx.Request("POST", "https://gateway.example.com")
        flex_error = (
            RateLimitError("busy", response=httpx.Response(429, request=request), body=None)
            if refused
            else APIConnectionError(request=request)
        )
        client = MagicMock()
        client.with_options.return_value = client
        client.chat.completions.create.side_effect = [
            flex_error,
            *[APIConnectionError(request=request)] * standard_failures,
            _completion(json.dumps({"evaluation_type": "hog", "name": "n", "description": "d", "body": "return true"})),
        ]

        with (
            patch.object(drafting, "build_openai_client", return_value=client),
            patch.object(drafting, "RETRY_BACKOFF_SECONDS", 0),
        ):
            call = drafting.draft_check(self.team.pk, brief)

        one_call = drafting.max_cost_usd(brief) / (2 + drafting.STANDARD_MAX_RETRIES)
        assert call.cost_usd == pytest.approx(served_cost + unsettled_calls * one_call)


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

        fail_run(str(run.id), "Activity task timed out")

        run.refresh_from_db()
        assert run.status == after

    def test_an_attempt_publishes_nothing_once_the_run_was_given_up(self) -> None:
        run = create_run(self.team, "scheduled")
        fail_run(str(run.id), "Activity task timed out")

        assert publish(run, [_candidate("check:unrecovered_errors", [])], {}) == []
        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.FAILED
        assert not EvalSuggestion.objects.for_team(self.team.pk).exists()

    def test_a_run_past_its_deadline_stops_before_publishing(self) -> None:
        run = create_run(self.team, "scheduled")

        with pytest.raises(pipeline.RunDeadlinePassed):
            execute_run(str(run.id), include_paid=False, settings=SuggestionSettings(), deadline=0.0)

        run.refresh_from_db()
        assert run.status == EvalSuggestionRunStatus.FAILED


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


@parameterized.expand([("judge_draft", "llm_judge"), ("hog_draft", "hog")])
def test_a_draft_replaces_the_templated_card_for_its_gap(
    _name: str, evaluation_type: Literal["hog", "llm_judge"]
) -> None:
    templated = _candidate("gap:review_lens=security:findings[].priority", [SECURITY_LENS], GAP_PROMPT)
    draft = drafting.Draft(evaluation_type=evaluation_type, name="Drafted", description="d", body="return true")
    hog_card = replace(_candidate("check:drafted_review_lens", []), kind="new_hog")
    with (
        patch.object(pipeline.drafting, "gap_brief", return_value="brief"),
        patch.object(pipeline, "paid_draft", return_value=drafting.DraftCall(draft=draft, cost_usd=0.01)),
        patch.object(pipeline, "measure", return_value=[MagicMock()]),
        patch.object(pipeline.ranking, "code_check_proposal", return_value=hog_card),
    ):
        result = pipeline._drafted_proposals(
            MagicMock(),
            MagicMock(),
            [(MagicMock(), templated)],
            MagicMock(),
            MagicMock(),
            SuggestionSettings(),
            pipeline._Stages(),
        )

    assert [p.dedupe_key for p in result] == [templated.dedupe_key]


def test_a_drafted_check_stops_at_the_first_trace_that_runs_too_long() -> None:
    templated = _candidate("gap:review_lens=security:findings[].priority", [SECURITY_LENS], GAP_PROMPT)
    draft = drafting.Draft(evaluation_type="hog", name="Drafted", description="d", body="return true")
    sample = MagicMock(traces=[MagicMock(held_out=False) for _ in range(20)])
    passing = MagicMock(failed=False, reasoning="ok")
    timed_out = MagicMock(failed=None, reasoning="Execution timed out (10s limit exceeded)")
    stages = pipeline._Stages()
    with (
        patch.object(pipeline.drafting, "gap_brief", return_value="brief"),
        patch.object(pipeline, "paid_draft", return_value=drafting.DraftCall(draft=draft, cost_usd=0.01)),
        patch.object(pipeline, "run_check", side_effect=[[passing]] * 7 + [[timed_out]]) as run_check,
    ):
        result = pipeline._drafted_proposals(
            MagicMock(), MagicMock(), [(MagicMock(), templated)], sample, MagicMock(), SuggestionSettings(), stages
        )

    assert result == []
    assert run_check.call_count == 8
    assert stages.record["drafting"] == {"status": "failed", "detail": "drafted Hog runs too long"}
