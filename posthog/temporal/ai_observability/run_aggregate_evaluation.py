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
from typing import Any, Literal

import temporalio
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.dataclasses import frozen
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
from posthog.temporal.ai_observability.run_session_evaluation import (
    ExecuteSessionEvaluationInputs,
    execute_session_hog_eval_activity,
    execute_session_llm_judge_activity,
    session_fetch_lookback,
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
    DEFAULT_SETTLE_STRATEGY_BY_TARGET,
    MAX_SESSION_EVAL_EVENTS,
    SESSION_EVAL_DEFAULT_MAX_AGE_SECONDS,
    SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_DEFAULT_WINDOW_SECONDS,
    SESSION_EVAL_MAX_MAX_AGE_SECONDS,
    SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MAX_WINDOW_SECONDS,
    SESSION_EVAL_MIN_MAX_AGE_SECONDS,
    SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MIN_WINDOW_SECONDS,
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
        increment_settle_poll("not_visible", target="trace")
        raise ApplicationError("no trace activity visible yet", type="trace_not_settled")
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    quiet_for = (datetime.now(UTC) - last_seen).total_seconds()
    if quiet_for < inputs.quiet_period_seconds + INGESTION_LAG_MARGIN_SECONDS:
        increment_settle_poll("not_settled", target="trace")
        raise ApplicationError(f"trace active {int(quiet_for)}s ago", type="trace_not_settled")
    increment_settle_poll("settled", target="trace")
    return last_seen.isoformat()


# Same liveness rules as the trace poll, keyed on session_id instead. `session_id` is
# Nullable(String), so equality against a non-null constant already excludes NULL rows.
#
# Access path differs from the trace poll: session_id is not in the sort key, so pruning is the
# team_id prefix plus the idx_session_id bloom filter (0.01 false-positive rate). The partition key
# is toYYYYMM(drop_date), which derives from timestamp plus a per-row retention_days, so no
# timestamp predicate prunes partitions — the _timestamp bound only filters within selected
# granules. count() rides the same scan, which is what makes the runaway-session guard free.
_SESSION_SETTLE_POLL_SQL = """
SELECT maxOrNull(_timestamp) AS last_seen, count() AS event_count
FROM posthog.ai_events AS ai_events
WHERE event IN {liveness_events}
  AND session_id = {session_id}
  AND _timestamp >= {date_from}
"""


# Whether a session is small enough to evaluate is decided by one number in one place: the fetch
# preflight's `MAX_SESSION_EVAL_EVENTS`, which counts exactly the rows the fetch reads, over the
# same window and clock. This is not that number. It is a circuit breaker whose only job is to stop
# a runaway session id (a constant "0", an id shared across every conversation) from holding a
# workflow open for its entire max_age. It counts liveness events over the settle window, so it
# undercounts a long session by construction — fine for a circuit breaker, and exactly why it must
# sit far above the evaluation cap rather than pretending to be it.
SESSION_RUNAWAY_CIRCUIT_BREAKER_EVENTS = 10 * MAX_SESSION_EVAL_EVENTS


@dataclass
class CheckSessionSettledInputs:
    team_id: int
    session_id: str
    quiet_period_seconds: int
    lookback_seconds: int
    runaway_events: int = SESSION_RUNAWAY_CIRCUIT_BREAKER_EVENTS

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "session_id": self.session_id}


@temporalio.activity.defn
@close_db_connections
def check_session_settled_activity(inputs: CheckSessionSettledInputs) -> str:
    """One settle probe for a session. Raises the retryable `session_not_settled` error until the
    session has had no structural activity for quiet_period + margin; the activity's retry
    schedule is the poll loop, so this function never sleeps."""
    team = Team.objects.get(id=inputs.team_id)
    # Tagged like every other AI-observability query so it routes to the LLM_ANALYTICS ClickHouse
    # user and takes its concurrency slot; untagged, a settling session's polls compete with
    # interactive traffic on the default user.
    with tags_context(product=Product.LLM_ANALYTICS):
        result = query_ai_events(
            query=parse_select(_SESSION_SETTLE_POLL_SQL),
            placeholders={
                "liveness_events": ast.Constant(value=list(_LIVENESS_EVENTS)),
                "session_id": ast.Constant(value=inputs.session_id),
                "date_from": ast.Constant(value=datetime.now(UTC) - timedelta(seconds=inputs.lookback_seconds)),
            },
            team=team,
            query_type="SessionSettlePoll",
            fall_back_to_events=False,
            workload=Workload.OFFLINE,
        )
    row = result.results[0] if result.results else (None, 0)
    last_seen, event_count = row[0], int(row[1] or 0)
    if event_count > inputs.runaway_events:
        # Stop waiting immediately rather than sitting out max_age. The fetch still decides the
        # actual outcome and reports the real reason; this only bounds how long we wait for it.
        increment_settle_poll("runaway", target="session")
        raise ApplicationError(
            f"session has {event_count} events in the settle window, over the "
            f"{inputs.runaway_events} runaway threshold",
            type="session_runaway",
            non_retryable=True,
        )
    if last_seen is None:
        increment_settle_poll("not_visible", target="session")
        raise ApplicationError("no session activity visible yet", type="session_not_settled")
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    quiet_for = (datetime.now(UTC) - last_seen).total_seconds()
    if quiet_for < inputs.quiet_period_seconds + INGESTION_LAG_MARGIN_SECONDS:
        increment_settle_poll("not_settled", target="session")
        raise ApplicationError(f"session active {int(quiet_for)}s ago", type="session_not_settled")
    increment_settle_poll("settled", target="session")
    return last_seen.isoformat()


def _clamp(value: Any, floor: int, ceiling: int, default: int) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return int(min(max(value, floor), ceiling))


# (floor, ceiling, default) per field, per target. The workflow re-clamps what the serializer
# already validated, so a payload written before a bound moved can never wedge the settle phase.
_SETTLE_BOUNDS: dict[str, dict[str, tuple[int, int, int]]] = {
    "trace": {
        "window": (TRACE_EVAL_MIN_WINDOW_SECONDS, TRACE_EVAL_MAX_WINDOW_SECONDS, TRACE_EVAL_DEFAULT_WINDOW_SECONDS),
        "quiet": (
            TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS,
            TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS,
            TRACE_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
        ),
        "max_age": (TRACE_EVAL_MIN_MAX_AGE_SECONDS, TRACE_EVAL_MAX_MAX_AGE_SECONDS, TRACE_EVAL_DEFAULT_MAX_AGE_SECONDS),
    },
    "session": {
        "window": (
            SESSION_EVAL_MIN_WINDOW_SECONDS,
            SESSION_EVAL_MAX_WINDOW_SECONDS,
            SESSION_EVAL_DEFAULT_WINDOW_SECONDS,
        ),
        "quiet": (
            SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
            SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
            SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
        ),
        "max_age": (
            SESSION_EVAL_MIN_MAX_AGE_SECONDS,
            SESSION_EVAL_MAX_MAX_AGE_SECONDS,
            SESSION_EVAL_DEFAULT_MAX_AGE_SECONDS,
        ),
    },
}


# Ceiling on poll activities per settling run. Sessions accept quiet=10s alongside max_age=7d, and
# a cadence derived from the quiet period alone would schedule ~60k ClickHouse aggregates for one
# (evaluation, session). Large enough that no in-bounds trace config is affected, so in-flight trace
# runs replay with an unchanged retry policy.
MAX_SETTLE_POLLS_PER_RUN = 1000


def resolve_poll_interval(primary_seconds: int, poll_budget_seconds: int) -> int:
    """Seconds between settle probes: a quarter of the quiet period, floored so a long max-age
    budget can't turn a short quiet period into tens of thousands of polls.

    The budget floor rounds up, so the ceiling holds exactly rather than off by one.
    """
    budget_floor = -(-poll_budget_seconds // MAX_SETTLE_POLLS_PER_RUN)
    return max(primary_seconds // 4, budget_floor, 10)


@frozen
class SettlePlan:
    strategy: Literal["inactivity", "fixed_window"]
    # The quiet period under inactivity, the window under fixed_window.
    primary_seconds: int
    max_age_seconds: int


def resolve_settle_plan(settle: dict[str, Any] | None, target: str = "trace") -> SettlePlan:
    """Resolve the settle config into a SettlePlan.

    Deterministic and exception-free on purpose: the serializer already validated the stored
    config, so anything malformed here is a payload bug — falling back to defaults keeps a bad
    payload from wedging the workflow. max_age is coerced to cover at least one quiet period.
    """
    bounds = _SETTLE_BOUNDS.get(target, _SETTLE_BOUNDS["trace"])
    config = settle or {}
    strategy = config.get("strategy") or DEFAULT_SETTLE_STRATEGY_BY_TARGET.get(target, "fixed_window")
    if strategy == "inactivity":
        quiet = _clamp(config.get("quiet_period_seconds"), *bounds["quiet"])
        max_age = _clamp(config.get("max_age_seconds"), *bounds["max_age"])
        return SettlePlan(strategy="inactivity", primary_seconds=quiet, max_age_seconds=max(max_age, quiet))
    window = _clamp(config.get("window_seconds"), *bounds["window"])
    return SettlePlan(strategy="fixed_window", primary_seconds=window, max_age_seconds=window)


@dataclass
class RunAggregateEvaluationInputs:
    evaluation_id: str
    team_id: int
    trace_id: str
    distinct_id: str
    session_id: str | None = None
    ai_session_id: str | None = None
    target: str = "trace"
    settle: dict[str, Any] | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        """Properties for PostHogClientInterceptor error capture."""
        return {
            "evaluation_id": self.evaluation_id,
            "team_id": self.team_id,
            "trace_id": self.trace_id,
            "target": self.target,
        }


def _is_schedule_to_close_timeout(error: temporalio.exceptions.ActivityError) -> bool:
    cause = error.cause
    return (
        isinstance(cause, temporalio.exceptions.TimeoutError)
        and cause.type == temporalio.exceptions.TimeoutType.SCHEDULE_TO_CLOSE
    )


# Both poll activities signal "keep waiting" with their own error type. This must stay a set
# rather than become a rename: `trace_not_settled` is recorded in the history of every in-flight
# trace run, and replay has to keep matching it.
_NOT_SETTLED_ERROR_TYPES = frozenset({"trace_not_settled", "session_not_settled"})


def _is_still_not_settled(error: temporalio.exceptions.ActivityError) -> bool:
    # Temporal delivers the last attempt's own failure once retries run out of
    # schedule-to-close budget rather than synthesizing a timeout — the first probe
    # fires immediately, so there's always a prior not-settled failure to report by
    # the time the budget is exhausted.
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type in _NOT_SETTLED_ERROR_TYPES


def _is_session_runaway(error: temporalio.exceptions.ActivityError) -> bool:
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type == "session_runaway"


@temporalio.workflow.defn(name="run-aggregate-evaluation")
class RunAggregateEvaluationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunAggregateEvaluationInputs:
        return RunAggregateEvaluationInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: RunAggregateEvaluationInputs) -> WorkflowResult:
        window_start = temporalio.workflow.now()

        # Fail loudly rather than falling through to the trace path, which would grade `trace_id`
        # and emit a trace-shaped verdict under a session evaluation's name. Unreachable from the
        # scheduler, which drops these as `no_ai_session_id`; this is the backstop for a malformed
        # payload or a manual start. Emits no command, so trace histories replay unchanged.
        if inputs.target == "session" and inputs.ai_session_id is None:
            raise ApplicationError(
                "A session-target evaluation needs an $ai_session_id", type="missing_ai_session_id", non_retryable=True
            )

        plan = resolve_settle_plan(inputs.settle, inputs.target)
        is_session = inputs.target == "session" and inputs.ai_session_id is not None
        if plan.strategy == "inactivity":
            # Sleep past the lag margin too: a probe at exactly quiet_period can never pass
            # the `quiet_period + margin` settled bar, so it would burn a poll for nothing.
            initial_sleep_seconds = min(plan.primary_seconds + INGESTION_LAG_MARGIN_SECONDS, plan.max_age_seconds)
            await asyncio.sleep(initial_sleep_seconds)
            poll_budget_seconds = plan.max_age_seconds - initial_sleep_seconds
            if poll_budget_seconds > 0:
                poll_interval = resolve_poll_interval(plan.primary_seconds, poll_budget_seconds)
                retry_policy = RetryPolicy(
                    initial_interval=timedelta(seconds=poll_interval),
                    backoff_coefficient=1.0,
                    maximum_attempts=0,
                )
                try:
                    if is_session and inputs.ai_session_id is not None:
                        await temporalio.workflow.execute_activity(
                            check_session_settled_activity,
                            CheckSessionSettledInputs(
                                team_id=inputs.team_id,
                                session_id=inputs.ai_session_id,
                                quiet_period_seconds=plan.primary_seconds,
                                lookback_seconds=int(session_fetch_lookback(plan.max_age_seconds).total_seconds()),
                            ),
                            start_to_close_timeout=timedelta(seconds=30),
                            schedule_to_close_timeout=timedelta(seconds=poll_budget_seconds),
                            retry_policy=retry_policy,
                        )
                    else:
                        await temporalio.workflow.execute_activity(
                            check_trace_settled_activity,
                            CheckTraceSettledInputs(
                                team_id=inputs.team_id,
                                trace_id=inputs.trace_id,
                                quiet_period_seconds=plan.primary_seconds,
                            ),
                            start_to_close_timeout=timedelta(seconds=30),
                            schedule_to_close_timeout=timedelta(seconds=poll_budget_seconds),
                            retry_policy=retry_policy,
                        )
                except temporalio.exceptions.ActivityError as e:
                    if _is_session_runaway(e):
                        # Stop waiting; the fetch's own preflight decides the outcome and reports
                        # the real reason, so no skip result has to be synthesized here.
                        pass
                    elif _is_schedule_to_close_timeout(e) or _is_still_not_settled(e):
                        # Temporal stops polling once the next retry would overrun schedule-to-close, so it
                        # can give up as much as one poll_interval before max_age. Wait out the remainder so
                        # we always honor the full max-age window before grading a still-active unit.
                        remaining = plan.max_age_seconds - (temporalio.workflow.now() - window_start).total_seconds()
                        if remaining > 0:
                            await asyncio.sleep(remaining)
                    else:
                        raise
        elif plan.primary_seconds:
            await asyncio.sleep(plan.primary_seconds)

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

        if is_session and inputs.ai_session_id is not None:
            session_inputs = ExecuteSessionEvaluationInputs(
                evaluation=evaluation,
                team_id=inputs.team_id,
                session_id=inputs.ai_session_id,
                window_start=window_start.isoformat(),
            )
            if evaluation_type == "hog":
                result = await temporalio.workflow.execute_activity(
                    execute_session_hog_eval_activity,
                    session_inputs,
                    # Longer than the trace equivalent: the fetch spans every trace of the session.
                    schedule_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            else:
                try:
                    result = await temporalio.workflow.execute_activity(
                        execute_session_llm_judge_activity,
                        session_inputs,
                        schedule_to_close_timeout=timedelta(minutes=15),
                        retry_policy=LLM_JUDGE_RETRY_POLICY,
                    )
                except temporalio.exceptions.ActivityError as e:
                    handled = await handle_llm_judge_activity_error(e, evaluation, evaluation_type)
                    if handled is not None:
                        return handled
                    raise
        else:
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
                    target=inputs.target,
                    ai_session_id=inputs.ai_session_id,
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
