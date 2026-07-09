import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.cdp.validation import compile_hog
from posthog.models import Organization, Team

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation

from .evaluation_llm_judge import BooleanEvalResult
from .evaluation_types import EvaluationActivityResult
from .run_trace_evaluation import (
    JUDGE_TRACE_MAX_CHARS,
    MAX_TRACE_EVAL_EVENTS,
    EmitTraceEvaluationEventInputs,
    ExecuteTraceEvaluationInputs,
    RunTraceEvaluationInputs,
    RunTraceEvaluationWorkflow,
    TraceFetchOutcome,
    _build_trace_skip_result,
    build_trace_hog_globals,
    build_trace_system_prompt,
    emit_trace_evaluation_event_activity,
    execute_trace_hog_eval_activity,
    execute_trace_llm_judge_activity,
    fetch_trace_for_evaluation,
    format_trace_for_judge,
)

FROZEN_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def create_trace_event(event: str = "$ai_generation", **properties: Any) -> LLMTraceEvent:
    return LLMTraceEvent(
        id=str(uuid.uuid4()),
        event=event,
        createdAt=FROZEN_NOW.isoformat(),
        properties=properties,
    )


def create_trace(events: list[LLMTraceEvent], **overrides: Any) -> LLMTrace:
    defaults: dict[str, Any] = {
        "id": "trace-123",
        "createdAt": FROZEN_NOW.isoformat(),
        "distinctId": "test-user",
        "events": events,
    }
    return LLMTrace(**{**defaults, **overrides})


@pytest.fixture
def setup_data():
    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    evaluation = Evaluation.objects.create(
        team=team,
        name="Trace Evaluation",
        evaluation_type="llm_judge",
        evaluation_config={"prompt": "Did the agent resolve the user's request?"},
        output_type="boolean",
        output_config={},
        target="trace",
        enabled=True,
    )
    return {"organization": organization, "team": team, "evaluation": evaluation}


@pytest.fixture
def grandfathered(setup_data, settings):
    # A team mid-trial before the cutoff keeps PostHog-funded inference, so trial/keyless judges run.
    settings.AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE = "2999-12-31T00:00:00+00:00"
    EvaluationConfig.objects.create(team=setup_data["team"], trial_eval_limit=100, trial_evals_used=50)


def evaluation_dict(setup_data: dict, **overrides: Any) -> dict[str, Any]:
    defaults = {
        "id": str(setup_data["evaluation"].id),
        "name": "Trace Evaluation",
        "evaluation_type": "llm_judge",
        "evaluation_config": {"prompt": "Did the agent resolve the user's request?"},
        "output_type": "boolean",
        "output_config": {},
        "team_id": setup_data["team"].id,
    }
    return {**defaults, **overrides}


# These assert the integration with the shared text_repr formatter — that the judge receives the
# trace's events and content — not the formatter's exact tree art, which text_repr tests itself.
class TestFormatTraceForJudge:
    def test_renders_trace_hierarchy_with_event_content(self):
        trace = create_trace(
            [
                create_trace_event(
                    "$ai_span",
                    **{"$ai_span_name": "retrieval", "$ai_input_state": "query", "$ai_output_state": "3 docs"},
                ),
                create_trace_event(
                    "$ai_generation",
                    **{
                        "$ai_model": "gpt-4o",
                        "$ai_latency": 1.5,
                        "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                        "$ai_output_choices": [{"role": "assistant", "content": "4"}],
                    },
                ),
            ],
            traceName="math-agent",
        )

        transcript = format_trace_for_judge(trace)

        assert "MATH-AGENT" in transcript
        assert "TRACE HIERARCHY" in transcript
        assert "[GEN]" in transcript
        assert "[SPAN]" in transcript
        assert "gpt-4o" in transcript
        assert "What is 2+2?" in transcript

    def test_includes_tool_catalog(self):
        tools = [{"type": "function", "function": {"name": "search_docs", "description": "Search the docs"}}]
        trace = create_trace(
            [
                create_trace_event("$ai_generation", **{"$ai_input": "hi", "$ai_output": "hello"}),
                create_trace_event("$ai_generation", **{"$ai_tools": tools, "$ai_input": "x", "$ai_output": "y"}),
            ]
        )

        transcript = format_trace_for_judge(trace)

        assert "search_docs" in transcript

    def test_truncates_long_event_io(self):
        trace = create_trace([create_trace_event("$ai_generation", **{"$ai_input": "x" * 50_000})])

        transcript = format_trace_for_judge(trace)

        assert "chars truncated" in transcript

    def test_bounds_output_to_max_chars(self):
        # 200 large generations would blow well past the cap without sampling.
        events = [
            create_trace_event("$ai_generation", **{"$ai_input": f"question {i} " + ("x" * 2_000)}) for i in range(200)
        ]

        transcript = format_trace_for_judge(create_trace(events))

        assert len(transcript) <= JUDGE_TRACE_MAX_CHARS

    def test_marks_errored_events(self):
        trace = create_trace(
            [create_trace_event("$ai_generation", **{"$ai_is_error": True, "$ai_error": "rate limited"})]
        )

        transcript = format_trace_for_judge(trace)

        assert "rate limited" in transcript


class TestBuildTraceHogGlobals:
    def test_builds_events_with_per_event_input_output(self):
        events = [
            create_trace_event("$ai_span", **{"$ai_input_state": "", "$ai_output_state": ""}),
            create_trace_event("$ai_generation", **{"$ai_input": "first question", "$ai_output": "first answer"}),
            create_trace_event("$ai_generation", **{"$ai_input": "second question", "$ai_output": "final answer"}),
        ]
        trace = create_trace(events)

        globals_dict = build_trace_hog_globals(trace, "trace-123")

        assert "input" not in globals_dict
        assert "output" not in globals_dict
        assert globals_dict["trace"] == {"id": "trace-123", "event_count": 3}
        assert len(globals_dict["events"]) == 3
        assert globals_dict["events"][1]["event"] == "$ai_generation"
        assert globals_dict["events"][1]["input"] == "first question"
        assert globals_dict["events"][2]["output"] == "final answer"

    def test_strips_heavy_keys_from_event_properties(self):
        events = [
            create_trace_event(
                "$ai_generation",
                **{"$ai_input": "question", "$ai_output": "answer", "$ai_model": "gpt-4o", "$ai_tools": ["tool"]},
            )
        ]
        trace = create_trace(events)

        globals_dict = build_trace_hog_globals(trace, "trace-123")

        event_props = globals_dict["events"][0]["properties"]
        assert event_props == {"$ai_model": "gpt-4o"}


class TestBuildTraceSkipResult:
    def test_skip_result_without_na(self):
        result = _build_trace_skip_result(allows_na=False, skip_reason="trace_too_large")

        assert result["verdict"] is False
        assert result["skipped"] is True
        assert result["skip_reason"] == "trace_too_large"
        assert "applicable" not in result

    def test_skip_result_with_na(self):
        result = _build_trace_skip_result(allows_na=True, skip_reason="trace_not_found")

        assert result["verdict"] is None
        assert result["applicable"] is False
        assert result["skip_reason"] == "trace_not_found"


class TestFetchTraceForEvaluation:
    @pytest.mark.django_db(transaction=True)
    def test_skips_when_no_events_found(self, setup_data):
        team = setup_data["team"]

        with patch("posthog.temporal.ai_observability.run_trace_evaluation._count_trace_events", return_value=0):
            outcome = fetch_trace_for_evaluation(team.id, "trace-123", FROZEN_NOW)

        assert outcome.skip_reason == "trace_not_found"
        assert outcome.trace is None

    @pytest.mark.django_db(transaction=True)
    def test_skips_oversized_traces_without_fetching(self, setup_data):
        team = setup_data["team"]

        with patch(
            "posthog.temporal.ai_observability.run_trace_evaluation._count_trace_events",
            return_value=MAX_TRACE_EVAL_EVENTS + 1,
        ):
            with patch("posthog.temporal.ai_observability.run_trace_evaluation.TraceQueryRunner") as mock_runner:
                outcome = fetch_trace_for_evaluation(team.id, "trace-123", FROZEN_NOW)

        assert outcome.skip_reason == "trace_too_large"
        assert outcome.event_count == MAX_TRACE_EVAL_EVENTS + 1
        mock_runner.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_returns_trace_when_found(self, setup_data):
        team = setup_data["team"]
        trace = create_trace([create_trace_event("$ai_generation", **{"$ai_input": "q", "$ai_output": "a"})])

        with patch("posthog.temporal.ai_observability.run_trace_evaluation._count_trace_events", return_value=1):
            with patch("posthog.temporal.ai_observability.run_trace_evaluation.TraceQueryRunner") as mock_runner:
                mock_runner.return_value.calculate.return_value = MagicMock(results=[trace])
                outcome = fetch_trace_for_evaluation(team.id, "trace-123", FROZEN_NOW)

        assert outcome.skip_reason is None
        assert outcome.trace is trace


class TestExecuteTraceLLMJudgeActivity:
    @pytest.mark.django_db(transaction=True)
    def test_judges_full_trace_transcript(self, setup_data, grandfathered):
        trace = create_trace(
            [
                create_trace_event("$ai_generation", **{"$ai_input": "What is 2+2?", "$ai_output": "4"}),
                create_trace_event("$ai_generation", **{"$ai_input": "And times 3?", "$ai_output": "12"}),
            ]
        )

        with patch(
            "posthog.temporal.ai_observability.run_trace_evaluation.fetch_trace_for_evaluation",
            return_value=TraceFetchOutcome(trace=trace, skip_reason=None, event_count=2),
        ):
            with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client_class.return_value = mock_client
                mock_response = MagicMock()
                mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Resolved both questions")
                mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
                mock_client.complete.return_value = mock_response

                result = execute_trace_llm_judge_activity(
                    ExecuteTraceEvaluationInputs(
                        evaluation=evaluation_dict(setup_data),
                        team_id=setup_data["team"].id,
                        trace_id="trace-123",
                        window_start=FROZEN_NOW.isoformat(),
                    )
                )

                request = mock_client.complete.call_args[0][0]
                content = request.messages[0]["content"]
                assert "AI trace" in request.system
                assert "TRACE HIERARCHY" in content
                assert content.count("[GEN]") == 2
                assert "What is 2+2?" in content
                assert "And times 3?" in content

        assert result["verdict"] is True
        assert result["reasoning"] == "Resolved both questions"

    @pytest.mark.django_db(transaction=True)
    def test_skips_without_llm_call_when_trace_missing(self, setup_data):
        with patch(
            "posthog.temporal.ai_observability.run_trace_evaluation.fetch_trace_for_evaluation",
            return_value=TraceFetchOutcome(trace=None, skip_reason="trace_not_found", event_count=0),
        ):
            with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
                result = execute_trace_llm_judge_activity(
                    ExecuteTraceEvaluationInputs(
                        evaluation=evaluation_dict(setup_data),
                        team_id=setup_data["team"].id,
                        trace_id="trace-123",
                        window_start=FROZEN_NOW.isoformat(),
                    )
                )

        assert result["skipped"] is True
        assert result["skip_reason"] == "trace_not_found"
        mock_client_class.assert_not_called()


class TestExecuteTraceHogEvalActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_runs_hog_against_trace_globals(self, setup_data):
        bytecode = compile_hog("return length(events) = 2 and events[2].output = 'final answer'", "destination")
        evaluation = evaluation_dict(
            setup_data,
            evaluation_type="hog",
            evaluation_config={"source": "...", "bytecode": bytecode},
        )
        trace = create_trace(
            [
                create_trace_event("$ai_generation", **{"$ai_input": "q1", "$ai_output": "intermediate"}),
                create_trace_event("$ai_generation", **{"$ai_input": "q2", "$ai_output": "final answer"}),
            ]
        )

        with patch(
            "posthog.temporal.ai_observability.run_trace_evaluation.fetch_trace_for_evaluation",
            return_value=TraceFetchOutcome(trace=trace, skip_reason=None, event_count=2),
        ):
            result = await execute_trace_hog_eval_activity(
                ExecuteTraceEvaluationInputs(
                    evaluation=evaluation,
                    team_id=setup_data["team"].id,
                    trace_id="trace-123",
                    window_start=FROZEN_NOW.isoformat(),
                )
            )

        assert result["verdict"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_skips_when_trace_too_large(self, setup_data):
        bytecode = compile_hog("return true", "destination")
        evaluation = evaluation_dict(
            setup_data,
            evaluation_type="hog",
            evaluation_config={"source": "return true", "bytecode": bytecode},
        )

        with patch(
            "posthog.temporal.ai_observability.run_trace_evaluation.fetch_trace_for_evaluation",
            return_value=TraceFetchOutcome(trace=None, skip_reason="trace_too_large", event_count=10_000),
        ):
            result = await execute_trace_hog_eval_activity(
                ExecuteTraceEvaluationInputs(
                    evaluation=evaluation,
                    team_id=setup_data["team"].id,
                    trace_id="trace-123",
                    window_start=FROZEN_NOW.isoformat(),
                )
            )

        assert result["skipped"] is True
        assert result["skip_reason"] == "trace_too_large"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_user_hog_error_is_terminal(self, setup_data):
        # A non-boolean return is a user Hog error; it must be terminal so the workflow disables
        # the broken eval instead of re-running it against every matching trace.
        bytecode = compile_hog("return 42", "destination")
        evaluation = evaluation_dict(
            setup_data,
            evaluation_type="hog",
            evaluation_config={"source": "return 42", "bytecode": bytecode},
        )
        trace = create_trace([create_trace_event("$ai_generation", **{"$ai_input": "q", "$ai_output": "a"})])

        with patch(
            "posthog.temporal.ai_observability.run_trace_evaluation.fetch_trace_for_evaluation",
            return_value=TraceFetchOutcome(trace=trace, skip_reason=None, event_count=1),
        ):
            result = await execute_trace_hog_eval_activity(
                ExecuteTraceEvaluationInputs(
                    evaluation=evaluation,
                    team_id=setup_data["team"].id,
                    trace_id="trace-123",
                    window_start=FROZEN_NOW.isoformat(),
                )
            )

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"]


class TestEmitTraceEvaluationEventActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emits_event_targeting_trace(self, setup_data):
        team = setup_data["team"]
        result: EvaluationActivityResult = {
            "result_type": "boolean",
            "verdict": True,
            "reasoning": "Looks good",
            "allows_na": False,
            "model": "gpt-5-mini",
            "provider": "openai",
            "input_tokens": 42,
            "output_tokens": 18,
        }

        with patch("posthog.temporal.ai_observability.run_trace_evaluation.Team.objects.get", return_value=team):
            with patch("posthog.temporal.ai_observability.run_trace_evaluation.capture_internal") as mock_capture:
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                await emit_trace_evaluation_event_activity(
                    EmitTraceEvaluationEventInputs(
                        evaluation=evaluation_dict(setup_data),
                        team_id=team.id,
                        trace_id="trace-123",
                        distinct_id="test-user",
                        session_id="session-1",
                        result=result,
                        start_time=datetime(2024, 1, 1, 12, 0, 0),
                    )
                )

                mock_capture.assert_called_once()
                call_kwargs = mock_capture.call_args[1]
                assert call_kwargs["event_name"] == "$ai_evaluation"
                assert call_kwargs["distinct_id"] == "test-user"
                props = call_kwargs["properties"]
                assert props["$ai_target_id"] == "trace-123"
                assert props["$ai_target_type"] == "trace_id"
                assert props["$ai_trace_id"] == "trace-123"
                assert props["$session_id"] == "session-1"
                assert props["$ai_evaluation_result"] is True
                assert props["$ai_model"] == "gpt-5-mini"
                assert "$ai_target_event_id" not in props
                assert "$ai_target_event_type" not in props


class TestRunTraceEvaluationWorkflowInputs:
    def test_parse_inputs(self):
        payload = {
            "evaluation_id": "eval-123",
            "team_id": 1,
            "trace_id": "trace-456",
            "distinct_id": "user-1",
            "session_id": None,
            "window_seconds": 60,
        }

        parsed = RunTraceEvaluationWorkflow.parse_inputs([json.dumps(payload)])

        assert parsed.evaluation_id == "eval-123"
        assert parsed.trace_id == "trace-456"
        assert parsed.window_seconds == 60

    def test_defaults(self):
        inputs = RunTraceEvaluationInputs(
            evaluation_id="eval-123", team_id=1, trace_id="trace-456", distinct_id="user-1"
        )

        assert inputs.session_id is None
        assert inputs.window_seconds == 30 * 60


class TestBuildTraceSystemPrompt:
    def test_frames_trace_as_unit_under_evaluation(self):
        prompt = build_trace_system_prompt("Did the agent resolve the request?", allows_na=False)

        assert "AI trace" in prompt
        assert "Did the agent resolve the request?" in prompt
        assert "boolean verdict" in prompt
