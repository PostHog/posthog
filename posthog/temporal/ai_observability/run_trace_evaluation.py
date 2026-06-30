"""Trace-level evaluation workflow.

The evaluation scheduler starts this workflow when the first $ai_generation matching a
trace-target evaluation arrives. The workflow id (`llma-trace-eval-{evaluation_id}-{trace_id}`)
plus the USE_EXISTING conflict policy make every later matching event of the same trace a
no-op while a run is pending or in flight, and ALLOW_DUPLICATE_FAILED_ONLY prevents
re-evaluating a trace once a run completed. The workflow sleeps for an aggregation window so
the rest of the trace can arrive, then pulls the whole trace from ClickHouse and evaluates it
in one shot.

Temporal payloads are capped at ~2 MiB, so trace content never flows through the workflow:
each execute activity fetches the trace itself and returns only the small verdict dict.
"""

import json
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import temporalio
import posthoganalytics
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.schema import DateRange, LLMTrace, QueryLogTags, TraceQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.api.capture import capture_internal
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_errors import (
    is_terminal_user_error_result,
    require_user_error_spec,
    status_reason_detail_for_terminal_user_error,
)
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io
from posthog.temporal.ai_observability.evaluation_hog import coerce_hog_io_value, execute_hog_eval_bytecode
from posthog.temporal.ai_observability.evaluation_llm_judge import (
    LLM_JUDGE_RETRY_POLICY,
    call_llm_judge,
    get_output_type_config,
)
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.evaluation_workflow_activities import (
    EmitInternalTelemetryInputs,
    RunEvaluationInputs,
    build_evaluation_event_properties,
    emit_internal_telemetry_activity,
    fetch_evaluation_activity,
)
from posthog.temporal.ai_observability.metrics import increment_emit_event_outcome, increment_errors
from posthog.temporal.ai_observability.run_evaluation import (
    WorkflowResult,
    handle_llm_judge_activity_error,
    handle_terminal_user_error_result,
    increment_trial_usage_and_notify,
)
from posthog.temporal.common.base import PostHogWorkflow

from products.ai_observability.backend.models.evaluation_configs import (
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
)
from products.ai_observability.backend.text_repr.formatters import (
    FormatterOptions,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

logger = structlog.get_logger(__name__)

# How far back from the workflow start to look for trace events. The trigger is the first
# *matching* generation, so earlier events of the same trace (spans, prior generations) are
# expected; client-set timestamps far in the past fall outside this window by design.
TRACE_EVENTS_LOOKBACK = timedelta(hours=24)

# Guard against degenerate traces (e.g. a bug attaching everything to trace id "0"): traces
# above this event count are skipped without fetching their payload.
MAX_TRACE_EVAL_EVENTS = 500

# Char budget for the judge transcript. The shared formatter defaults to ~2M chars (sized to
# fill an LLM context window for summarization); a per-trace judge verdict doesn't need that
# much, so we cap lower to bound cost. Over budget, the formatter uniformly samples lines.
JUDGE_TRACE_MAX_CHARS = 150_000

# Heavy payload keys are dropped from per-event `properties` in Hog globals — their content
# is already exposed via the per-event `input`/`output` strings, and duplicating them doubles
# HogVM memory pressure on large traces.
HEAVY_TRACE_PROPERTY_KEYS = (
    "$ai_input",
    "$ai_output",
    "$ai_output_choices",
    "$ai_input_state",
    "$ai_output_state",
    "$ai_tools",
)

# Written against ai_events; query_ai_events rewrites it for the events table when ai_events
# returns nothing. HAVING makes a zero count return no rows, which both triggers the events-table
# fallback and keeps "no events" distinguishable without a second query.
_TRACE_EVENT_COUNT_SQL = """
SELECT count() AS event_count
FROM posthog.ai_events AS ai_events
WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
  AND trace_id = {trace_id}
  AND timestamp >= {date_from}
  AND timestamp <= {date_to}
HAVING event_count > 0
"""

_SKIP_REASONING = {
    "trace_not_found": "No trace events were found within the evaluation window; evaluation skipped.",
    "trace_too_large": (
        f"Trace exceeds {MAX_TRACE_EVAL_EVENTS} events — likely a shared or runaway trace id; evaluation skipped."
    ),
}


@dataclass
class RunTraceEvaluationInputs:
    evaluation_id: str
    team_id: int
    trace_id: str
    distinct_id: str
    session_id: str | None = None
    window_seconds: int = TRACE_EVAL_DEFAULT_WINDOW_SECONDS

    @property
    def properties_to_log(self) -> dict[str, Any]:
        """Properties for PostHogClientInterceptor error capture."""
        return {
            "evaluation_id": self.evaluation_id,
            "team_id": self.team_id,
            "trace_id": self.trace_id,
        }


@dataclass
class ExecuteTraceEvaluationInputs:
    evaluation: dict[str, Any]
    team_id: int
    trace_id: str
    window_start: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "evaluation_id": self.evaluation.get("id"),
            "trace_id": self.trace_id,
        }


@dataclass
class TraceFetchOutcome:
    trace: LLMTrace | None
    skip_reason: str | None
    event_count: int


def _count_trace_events(team: Team, trace_id: str, date_from: datetime, date_to: datetime) -> int:
    result = query_ai_events(
        query=parse_select(_TRACE_EVENT_COUNT_SQL),
        placeholders={
            "trace_id": ast.Constant(value=trace_id),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        },
        team=team,
        query_type="TraceEvaluationEventCount",
        fall_back_to_events=True,
    )
    if not result.results:
        return 0
    return int(result.results[0][0])


def fetch_trace_for_evaluation(team_id: int, trace_id: str, window_start: datetime) -> TraceFetchOutcome:
    """Fetch the full trace from ClickHouse, with a cheap count preflight so degenerate
    traces are skipped before pulling their payload."""
    team = Team.objects.get(id=team_id)
    date_from = window_start - TRACE_EVENTS_LOOKBACK
    date_to = datetime.now(UTC)

    event_count = _count_trace_events(team, trace_id, date_from, date_to)
    if event_count == 0:
        return TraceFetchOutcome(trace=None, skip_reason="trace_not_found", event_count=0)
    if event_count > MAX_TRACE_EVAL_EVENTS:
        return TraceFetchOutcome(trace=None, skip_reason="trace_too_large", event_count=event_count)

    runner = TraceQueryRunner(
        team=team,
        query=TraceQuery(
            traceId=trace_id,
            dateRange=DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat()),
            tags=QueryLogTags(productKey="AIObservability"),
        ),
    )
    response = runner.calculate()
    if not response.results:
        return TraceFetchOutcome(trace=None, skip_reason="trace_not_found", event_count=event_count)
    return TraceFetchOutcome(trace=response.results[0], skip_reason=None, event_count=event_count)


def _build_trace_skip_result(allows_na: bool, skip_reason: str) -> EvaluationActivityResult:
    """Mirror of `_build_errored_trace_result` for trace-level skips — no LLM call is made,
    so model/provider are omitted and downstream cost attribution stays clean."""
    result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": None if allows_na else False,
        "reasoning": _SKIP_REASONING.get(skip_reason, "Evaluation skipped."),
        "allows_na": allows_na,
        "skipped": True,
        "skip_reason": skip_reason,
    }
    if allows_na:
        result["applicable"] = False
    return result


def build_trace_system_prompt(prompt: str, allows_na: bool) -> str:
    """Trace-level variant of `build_system_prompt` — frames the unit under evaluation as the
    whole trace rather than a single generation."""
    config = get_output_type_config(allows_na)
    return f"""You are an evaluator. Evaluate the following AI trace — the full sequence of LLM calls and operations from one execution — according to this criteria:

{prompt}

{config.instructions}"""


def format_trace_for_judge(trace: LLMTrace) -> str:
    """Serialize a trace into the canonical text representation for the LLM judge.

    Delegates to the shared `text_repr` formatter — the same plain-text rendering the trace
    view shows users and the trace-summarization workflow feeds its own LLM. Using it here
    means the judge grades exactly what a user sees when they open the trace to debug a
    verdict, and there's one trace serializer to maintain across the product, not a private
    fork. `include_markers=False` drops the frontend expand/collapse markers; the output is
    uniformly sampled down to `JUDGE_TRACE_MAX_CHARS` to bound judge cost and context.
    """
    trace_dict, hierarchy = llm_trace_to_formatter_format(trace)
    options: FormatterOptions = {
        "include_markers": False,
        "collapsed": False,
        "truncated": True,
        "include_line_numbers": True,
        "max_length": JUDGE_TRACE_MAX_CHARS,
    }
    text, _ = format_trace_text_repr(trace_dict, hierarchy, options)
    return text


def build_trace_hog_globals(trace: LLMTrace, trace_id: str) -> dict[str, Any]:
    """Build Hog globals for a trace-level eval.

    `events` carries every trace event in chronological order with stringified input/output.
    Sources read per-event io off `events`; there is no trace-level `input`/`output` because
    a single synthesized pair isn't meaningful across a whole trace and wouldn't match what
    the trace view shows.
    """
    events_globals: list[dict[str, Any]] = []
    for event in trace.events or []:
        props = event.properties
        input_raw, output_raw = extract_event_io(event.event, props)
        events_globals.append(
            {
                "uuid": event.id,
                "event": event.event,
                "timestamp": event.createdAt,
                "input": coerce_hog_io_value(input_raw),
                "output": coerce_hog_io_value(output_raw),
                "properties": {k: v for k, v in props.items() if k not in HEAVY_TRACE_PROPERTY_KEYS},
            }
        )
    return {
        "events": events_globals,
        "trace": {"id": trace_id, "event_count": len(events_globals)},
    }


@temporalio.activity.defn
@posthoganalytics.scoped()
def execute_trace_llm_judge_activity(inputs: ExecuteTraceEvaluationInputs) -> EvaluationActivityResult:
    """Fetch the whole trace and run the LLM judge over its transcript.

    Fetch and judge happen in one activity on purpose: returning the trace through the
    workflow would hit Temporal's ~2 MiB payload limit on large traces.
    """
    evaluation = inputs.evaluation

    if evaluation["evaluation_type"] != "llm_judge":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    prompt = evaluation.get("evaluation_config", {}).get("prompt")
    if not prompt:
        raise ApplicationError("Missing prompt in evaluation_config", non_retryable=True)

    if evaluation["output_type"] != "boolean":
        raise ApplicationError(
            f"Unsupported output type: {evaluation['output_type']}. Supported types: 'boolean'.",
            non_retryable=True,
        )

    allows_na = evaluation.get("output_config", {}).get("allows_na", False)

    outcome = fetch_trace_for_evaluation(inputs.team_id, inputs.trace_id, datetime.fromisoformat(inputs.window_start))
    if outcome.skip_reason or outcome.trace is None:
        return _build_trace_skip_result(allows_na, outcome.skip_reason or "trace_not_found")

    return call_llm_judge(
        evaluation=evaluation,
        system_prompt=build_trace_system_prompt(prompt, allows_na),
        user_prompt=format_trace_for_judge(outcome.trace),
        allows_na=allows_na,
    )


@temporalio.activity.defn
async def execute_trace_hog_eval_activity(inputs: ExecuteTraceEvaluationInputs) -> EvaluationActivityResult:
    """Fetch the whole trace and run Hog bytecode against trace-level globals."""
    evaluation = inputs.evaluation

    if evaluation["evaluation_type"] != "hog":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    bytecode = evaluation.get("evaluation_config", {}).get("bytecode")
    if not bytecode:
        raise ApplicationError("Missing bytecode in evaluation_config", non_retryable=True)

    allows_na = evaluation.get("output_config", {}).get("allows_na", False)

    def _execute() -> tuple[dict[str, Any] | None, str | None]:
        outcome = fetch_trace_for_evaluation(
            inputs.team_id, inputs.trace_id, datetime.fromisoformat(inputs.window_start)
        )
        if outcome.skip_reason or outcome.trace is None:
            return None, outcome.skip_reason or "trace_not_found"
        globals_dict = build_trace_hog_globals(outcome.trace, inputs.trace_id)
        return execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=allows_na), None

    result, skip_reason = await database_sync_to_async(_execute, thread_sensitive=False)()

    if skip_reason or result is None:
        return _build_trace_skip_result(allows_na, skip_reason or "trace_not_found")

    if result["error"]:
        if result.get("unexpected"):
            # A genuine bug in our evaluation code (not the user's Hog). Raise so the Temporal
            # interceptor reports it to error tracking and we get paged to investigate.
            raise ApplicationError(
                f"Hog evaluation error: {result['error']}",
                non_retryable=True,
            )

        # The user's Hog source itself errored — an expected outcome of running customer-authored
        # code, recorded as a skipped evaluation rather than raised (which would flood error
        # tracking with one event per trace). Marked terminal so the workflow disables the broken
        # eval instead of re-running it against every matching trace (mirrors the generation path).
        spec = require_user_error_spec("hog_error")
        error_detail = status_reason_detail_for_terminal_user_error(spec, result["error"]) or spec.safe_message
        errored_result: EvaluationActivityResult = {
            "result_type": "boolean",
            "verdict": None if allows_na else False,
            "reasoning": error_detail,
            "allows_na": allows_na,
            "skipped": True,
            "skip_reason": "hog_error",
            "terminal_user_error": True,
            "status_reason": spec.status_reason,
        }
        if allows_na:
            errored_result["applicable"] = False
        return errored_result

    activity_result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": result["verdict"],
        "reasoning": result["reasoning"],
        "allows_na": allows_na,
    }
    if allows_na:
        activity_result["applicable"] = result.get("applicable", True)
    return activity_result


@dataclass
class EmitTraceEvaluationEventInputs:
    evaluation: dict[str, Any]
    team_id: int
    trace_id: str
    distinct_id: str
    session_id: str | None
    result: EvaluationActivityResult
    start_time: datetime

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "evaluation_id": self.evaluation.get("id"),
            "trace_id": self.trace_id,
        }


@temporalio.activity.defn
async def emit_trace_evaluation_event_activity(inputs: EmitTraceEvaluationEventInputs) -> None:
    """Emit the $ai_evaluation event for a trace-level run, targeting the trace id."""

    def _emit():
        try:
            team = Team.objects.get(id=inputs.team_id)
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=inputs.team_id)
            raise ValueError(f"Team {inputs.team_id} not found")

        # No single source event to inherit from, so SOURCE_AI_PROPERTIES_TO_COPY (span/parent
        # linkage copied in the generation path) intentionally does not apply here.
        properties = build_evaluation_event_properties(inputs.evaluation, inputs.result, inputs.start_time)
        properties.update(
            {
                "$ai_target_id": inputs.trace_id,
                "$ai_target_type": "trace_id",
                # The eval event carries the trace id itself so it shows up inside the trace view.
                "$ai_trace_id": inputs.trace_id,
                "$session_id": inputs.session_id,
            }
        )

        capture_result = capture_internal(
            token=team.api_token,
            event_name="$ai_evaluation",
            event_source="llm_analytics_evaluation",
            distinct_id=inputs.distinct_id,
            timestamp=datetime.now(UTC),
            properties=properties,
            process_person_profile=True,
        )
        capture_result.raise_for_status()

    try:
        await database_sync_to_async(_emit, thread_sensitive=False)()
        increment_emit_event_outcome("success")
    except Exception:
        increment_emit_event_outcome("failed")
        raise


@temporalio.workflow.defn(name="run-trace-evaluation")
class RunTraceEvaluationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunTraceEvaluationInputs:
        return RunTraceEvaluationInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: RunTraceEvaluationInputs) -> WorkflowResult:
        window_start = temporalio.workflow.now()

        # Wait for the rest of the trace to arrive. Timers are server-side, so sleeping
        # workflows don't hold worker slots.
        window_seconds = min(max(inputs.window_seconds, 0), TRACE_EVAL_MAX_WINDOW_SECONDS)
        if window_seconds:
            await asyncio.sleep(window_seconds)

        eval_start = temporalio.workflow.now()

        evaluation = await temporalio.workflow.execute_activity(
            fetch_evaluation_activity,
            RunEvaluationInputs(evaluation_id=inputs.evaluation_id, event_data={"team_id": inputs.team_id}),
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        evaluation_type = evaluation.get("evaluation_type", "llm_judge")

        # The evaluation may have been paused or deleted during the aggregation window —
        # bail out instead of running against config the user just turned off.
        if evaluation["deleted"] or not evaluation["enabled"]:
            disabled_result: WorkflowResult = {
                "verdict": None,
                "skipped": True,
                "skip_reason": "evaluation_deleted" if evaluation["deleted"] else "evaluation_disabled",
                "evaluation_id": inputs.evaluation_id,
                "evaluation_type": evaluation_type,
            }
            return disabled_result

        execute_inputs = ExecuteTraceEvaluationInputs(
            evaluation=evaluation,
            team_id=inputs.team_id,
            trace_id=inputs.trace_id,
            window_start=window_start.isoformat(),
        )

        if evaluation_type == "hog":
            # Unlike single-event hog evals, this activity includes a ClickHouse fetch, so
            # allow one retry for transient query failures (the bytecode is deterministic).
            result = await temporalio.workflow.execute_activity(
                execute_trace_hog_eval_activity,
                execute_inputs,
                schedule_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        else:
            try:
                result = await temporalio.workflow.execute_activity(
                    execute_trace_llm_judge_activity,
                    execute_inputs,
                    # > single-event judge timeout: the activity also fetches the trace from ClickHouse
                    schedule_to_close_timeout=timedelta(minutes=8),
                    retry_policy=LLM_JUDGE_RETRY_POLICY,
                )
            except temporalio.exceptions.ActivityError as e:
                handled = await handle_llm_judge_activity_error(e, evaluation, evaluation_type)
                if handled is not None:
                    return handled
                raise

            # Trial quota: same gating as the single-event workflow — only PostHog-key LLM
            # judge runs that actually called the API consume quota.
            if not result.get("is_byok") and not result.get("skipped"):
                await increment_trial_usage_and_notify(evaluation)

        if is_terminal_user_error_result(result):
            return await handle_terminal_user_error_result(
                evaluation=evaluation,
                evaluation_type=evaluation_type,
                result=result,
            )

        try:
            await temporalio.workflow.execute_activity(
                emit_trace_evaluation_event_activity,
                EmitTraceEvaluationEventInputs(
                    evaluation=evaluation,
                    team_id=inputs.team_id,
                    trace_id=inputs.trace_id,
                    distinct_id=inputs.distinct_id,
                    session_id=inputs.session_id,
                    result=result,
                    start_time=eval_start,
                ),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            increment_errors("emit_evaluation_event_failed", provider=result.get("provider"))
            raise

        if not result.get("skipped"):
            await temporalio.workflow.execute_activity(
                emit_internal_telemetry_activity,
                EmitInternalTelemetryInputs(
                    evaluation=evaluation,
                    team_id=inputs.team_id,
                    result=result,
                ),
                schedule_to_close_timeout=timedelta(seconds=30),
            )

        workflow_result: WorkflowResult = {
            "verdict": result["verdict"],
            "reasoning": result["reasoning"],
            "evaluation_id": evaluation["id"],
            "evaluation_type": evaluation_type,
            "is_byok": result.get("is_byok", False),
            "skipped": result.get("skipped", False),
        }
        if result.get("skipped"):
            skip_reason = result.get("skip_reason")
            if skip_reason is not None:
                workflow_result["skip_reason"] = skip_reason
        return workflow_result
