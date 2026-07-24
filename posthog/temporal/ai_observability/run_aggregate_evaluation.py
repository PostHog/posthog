"""Aggregate evaluation workflow: a settling phase in front of the shared trace-evaluation body.

Successor to `run-trace-evaluation`. The scheduler starts this workflow once per
(evaluation, trace) pair on the first condition-matching generation. Under the fixed_window
strategy the workflow just sleeps for the configured window, matching the old workflow's
behavior exactly. Under inactivity it sleeps one quiet period, then polls
`check_trace_settled_activity` — the activity itself raises a retryable error until the trace
has gone quiet, so the activity's retry schedule *is* the poll loop — with the remaining
max-age budget as the schedule-to-close timeout, which doubles as the hard cap on how long
polling can run. Workflow id scheme and dedup policies are unchanged, so a trace is still
evaluated at most once per evaluation.

The old workflow stays registered until its in-flight runs drain (bounded by the 2h max
window), then gets removed in a follow-up.
"""

import json
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import temporalio
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.models.team import Team
from posthog.temporal.ai_observability.evaluation_errors import is_terminal_user_error_result
from posthog.temporal.ai_observability.evaluation_llm_judge import LLM_JUDGE_RETRY_POLICY
from posthog.temporal.ai_observability.evaluation_workflow_activities import (
    EmitInternalTelemetryInputs,
    RunEvaluationInputs,
    emit_internal_telemetry_activity,
    fetch_evaluation_activity,
)
from posthog.temporal.ai_observability.metrics import increment_errors, increment_settle_poll
from posthog.temporal.ai_observability.run_evaluation import (
    WorkflowResult,
    handle_llm_judge_activity_error,
    handle_terminal_user_error_result,
)
from posthog.temporal.ai_observability.run_trace_evaluation import (
    TRACE_EVENTS_LOOKBACK,
    EmitTraceEvaluationEventInputs,
    ExecuteTraceEvaluationInputs,
    emit_trace_evaluation_event_activity,
    execute_trace_hog_eval_activity,
    execute_trace_llm_judge_activity,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.utils import close_db_connections

from products.ai_observability.backend.models.evaluation_configs import (
    TRACE_EVAL_DEFAULT_MAX_AGE_SECONDS,
    TRACE_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_MAX_AGE_SECONDS,
    TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
    TRACE_EVAL_MIN_MAX_AGE_SECONDS,
    TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_MIN_WINDOW_SECONDS,
)

INGESTION_LAG_MARGIN_SECONDS = 15

# Structural trace activity only: $ai_evaluation / $ai_feedback / $ai_metric are post-hoc
# annotations — another eval's verdict or late user feedback must not defer settling.
_LIVENESS_EVENTS = ("$ai_generation", "$ai_span", "$ai_embedding", "$ai_trace")

# ai_events only, never the events fallback: every AI event is double-written there for all
# teams, and the fallback's events-table scan is orders of magnitude more expensive. The query
# must also stay ungrouped: an ungrouped aggregate always returns exactly one row, so
# query_ai_events's empty-result probe (which triggers the fallback) never fires.
#
# The date_from guard bounds by ARRIVAL time (_timestamp), not the client-set `timestamp`, so a
# backdated event (clock skew, historical backfill) can't hide activity from the poll by landing
# outside a timestamp-based window while still arriving now. The (team_id, trace_id) sort-key
# prefix still does the pruning; _timestamp only filters in-scan within the trace's granules.
_SETTLE_POLL_SQL = """
SELECT maxOrNull(_timestamp) AS last_seen
FROM posthog.ai_events AS ai_events
WHERE event IN {liveness_events}
  AND trace_id = {trace_id}
  AND _timestamp >= {date_from}
"""


@dataclass
class CheckTraceSettledInputs:
    team_id: int
    trace_id: str
    quiet_period_seconds: int

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "trace_id": self.trace_id}


@temporalio.activity.defn
@close_db_connections
def check_trace_settled_activity(inputs: CheckTraceSettledInputs) -> str:
    """One settle probe. Raises the retryable `trace_not_settled` error until the trace has
    had no structural activity for quiet_period + margin; the activity's retry schedule is
    the poll loop, so this function never sleeps."""
    team = Team.objects.get(id=inputs.team_id)
    result = query_ai_events(
        query=parse_select(_SETTLE_POLL_SQL),
        placeholders={
            "liveness_events": ast.Constant(value=list(_LIVENESS_EVENTS)),
            "trace_id": ast.Constant(value=inputs.trace_id),
            "date_from": ast.Constant(value=datetime.now(UTC) - TRACE_EVENTS_LOOKBACK),
        },
        team=team,
        query_type="TraceSettlePoll",
        fall_back_to_events=False,
        workload=Workload.OFFLINE,
    )
    last_seen = result.results[0][0] if result.results else None
    if last_seen is None:
        # Nothing visible yet (ingestion lag, replica flap, or a trace that never reached
        # ClickHouse): keep polling — the max-age cap is the backstop. Settling on NULL
        # would manufacture a trace_not_found verdict out of a lag spike.
        increment_settle_poll("not_visible")
        raise ApplicationError("no trace activity visible yet", type="trace_not_settled")
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    quiet_for = (datetime.now(UTC) - last_seen).total_seconds()
    if quiet_for < inputs.quiet_period_seconds + INGESTION_LAG_MARGIN_SECONDS:
        increment_settle_poll("not_settled")
        raise ApplicationError(f"trace active {int(quiet_for)}s ago", type="trace_not_settled")
    increment_settle_poll("settled")
    return last_seen.isoformat()


def _clamp(value: Any, floor: int, ceiling: int, default: int) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return int(min(max(value, floor), ceiling))


def resolve_settle_plan(settle: dict[str, Any] | None) -> tuple[str, int, int]:
    """Resolve the settle config into (strategy, primary_seconds, max_age_seconds).

    Deterministic and exception-free on purpose: the serializer already validated the stored
    config, so anything malformed here is a payload bug — falling back to defaults keeps a bad
    payload from wedging the workflow. max_age is coerced to cover at least one quiet period.
    """
    config = settle or {}
    if config.get("strategy") == "inactivity":
        quiet = _clamp(
            config.get("quiet_period_seconds"),
            TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS,
            TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS,
            TRACE_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
        )
        max_age = _clamp(
            config.get("max_age_seconds"),
            TRACE_EVAL_MIN_MAX_AGE_SECONDS,
            TRACE_EVAL_MAX_MAX_AGE_SECONDS,
            TRACE_EVAL_DEFAULT_MAX_AGE_SECONDS,
        )
        return ("inactivity", quiet, max(max_age, quiet))
    window = _clamp(
        config.get("window_seconds"),
        TRACE_EVAL_MIN_WINDOW_SECONDS,
        TRACE_EVAL_MAX_WINDOW_SECONDS,
        TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    )
    return ("fixed_window", window, window)


@dataclass
class RunAggregateEvaluationInputs:
    evaluation_id: str
    team_id: int
    trace_id: str
    distinct_id: str
    session_id: str | None = None
    settle: dict[str, Any] | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        """Properties for PostHogClientInterceptor error capture."""
        return {
            "evaluation_id": self.evaluation_id,
            "team_id": self.team_id,
            "trace_id": self.trace_id,
        }


def _is_schedule_to_close_timeout(error: temporalio.exceptions.ActivityError) -> bool:
    cause = error.cause
    return (
        isinstance(cause, temporalio.exceptions.TimeoutError)
        and cause.type == temporalio.exceptions.TimeoutType.SCHEDULE_TO_CLOSE
    )


def _is_still_not_settled(error: temporalio.exceptions.ActivityError) -> bool:
    # Temporal delivers the last attempt's own failure once retries run out of
    # schedule-to-close budget rather than synthesizing a timeout — the first probe
    # fires immediately, so there's always a prior `trace_not_settled` failure to
    # report by the time the budget is exhausted.
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type == "trace_not_settled"


@temporalio.workflow.defn(name="run-aggregate-evaluation")
class RunAggregateEvaluationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunAggregateEvaluationInputs:
        return RunAggregateEvaluationInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: RunAggregateEvaluationInputs) -> WorkflowResult:
        window_start = temporalio.workflow.now()

        strategy, primary_seconds, max_age_seconds = resolve_settle_plan(inputs.settle)
        if strategy == "inactivity":
            # Sleep past the lag margin too: a probe at exactly quiet_period can never pass
            # the `quiet_period + margin` settled bar, so it would burn a poll for nothing.
            initial_sleep_seconds = min(primary_seconds + INGESTION_LAG_MARGIN_SECONDS, max_age_seconds)
            await asyncio.sleep(initial_sleep_seconds)
            poll_budget_seconds = max_age_seconds - initial_sleep_seconds
            if poll_budget_seconds > 0:
                poll_interval = max(primary_seconds // 4, 10)
                try:
                    await temporalio.workflow.execute_activity(
                        check_trace_settled_activity,
                        CheckTraceSettledInputs(
                            team_id=inputs.team_id,
                            trace_id=inputs.trace_id,
                            quiet_period_seconds=primary_seconds,
                        ),
                        start_to_close_timeout=timedelta(seconds=30),
                        schedule_to_close_timeout=timedelta(seconds=poll_budget_seconds),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=poll_interval),
                            backoff_coefficient=1.0,
                            maximum_attempts=0,
                        ),
                    )
                except temporalio.exceptions.ActivityError as e:
                    # A schedule-to-close or still-not-settled timeout means the trace never settled
                    # within max_age — anything else is a real failure and should propagate.
                    if not (_is_schedule_to_close_timeout(e) or _is_still_not_settled(e)):
                        raise
                    # Temporal stops polling once the next retry would overrun schedule-to-close, so it
                    # can give up as much as one poll_interval before max_age. Wait out the remainder so
                    # we always honor the full max-age window before grading a still-active trace.
                    remaining = max_age_seconds - (temporalio.workflow.now() - window_start).total_seconds()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
        elif primary_seconds:
            await asyncio.sleep(primary_seconds)

        eval_start = temporalio.workflow.now()

        evaluation = await temporalio.workflow.execute_activity(
            fetch_evaluation_activity,
            RunEvaluationInputs(evaluation_id=inputs.evaluation_id, event_data={"team_id": inputs.team_id}),
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        evaluation_type = evaluation.get("evaluation_type", "llm_judge")

        # The evaluation may have been paused or deleted during the settle phase —
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
