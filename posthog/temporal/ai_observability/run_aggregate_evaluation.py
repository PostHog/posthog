"""Aggregate evaluation workflow: a settling phase in front of the shared trace-evaluation body.

Successor to `run-trace-evaluation`. The scheduler signal-with-starts this workflow for every
condition-matching generation of an (evaluation, trace) pair: the first one creates it, later
ones deliver an `activity-seen` signal. Under the fixed_window strategy signals are ignored,
matching the old workflow's behavior exactly; under inactivity each signal re-arms a
quiet-period timer bounded by a hard max age. Workflow id scheme and dedup policies are
unchanged, so a trace is still evaluated at most once per evaluation.

The old workflow stays registered until its in-flight runs drain (bounded by the 2h max
window), then gets removed in a follow-up.
"""

import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.ai_observability.evaluation_errors import is_terminal_user_error_result
from posthog.temporal.ai_observability.evaluation_llm_judge import LLM_JUDGE_RETRY_POLICY
from posthog.temporal.ai_observability.evaluation_workflow_activities import (
    EmitInternalTelemetryInputs,
    RunEvaluationInputs,
    emit_internal_telemetry_activity,
    fetch_evaluation_activity,
)
from posthog.temporal.ai_observability.metrics import increment_errors
from posthog.temporal.ai_observability.run_evaluation import (
    WorkflowResult,
    handle_llm_judge_activity_error,
    handle_terminal_user_error_result,
)
from posthog.temporal.ai_observability.run_trace_evaluation import (
    EmitTraceEvaluationEventInputs,
    ExecuteTraceEvaluationInputs,
    emit_trace_evaluation_event_activity,
    execute_trace_hog_eval_activity,
    execute_trace_llm_judge_activity,
)
from posthog.temporal.common.base import PostHogWorkflow

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


@temporalio.workflow.defn(name="run-aggregate-evaluation")
class RunAggregateEvaluationWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._last_activity_at: datetime | None = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunAggregateEvaluationInputs:
        return RunAggregateEvaluationInputs(**json.loads(inputs[0]))

    @temporalio.workflow.signal(name="activity-seen")
    def activity_seen(self, payload: dict[str, Any] | None = None) -> None:
        self._last_activity_at = temporalio.workflow.now()

    async def _settle(self, strategy: str, primary_seconds: int, max_age_seconds: int, window_start: datetime) -> None:
        if strategy != "inactivity":
            if primary_seconds:
                await asyncio.sleep(primary_seconds)
            return

        hard_deadline = window_start + timedelta(seconds=max_age_seconds)
        last_activity = window_start
        while True:
            deadline = min(last_activity + timedelta(seconds=primary_seconds), hard_deadline)
            now = temporalio.workflow.now()
            if deadline <= now:
                return

            def has_newer_activity(since: datetime = last_activity) -> bool:
                return self._last_activity_at is not None and self._last_activity_at > since

            try:
                await temporalio.workflow.wait_condition(
                    has_newer_activity,
                    timeout=(deadline - now).total_seconds(),
                )
            except TimeoutError:
                return
            if self._last_activity_at is not None:
                last_activity = self._last_activity_at

    @temporalio.workflow.run
    async def run(self, inputs: RunAggregateEvaluationInputs) -> WorkflowResult:
        window_start = temporalio.workflow.now()

        strategy, primary_seconds, max_age_seconds = resolve_settle_plan(inputs.settle)
        await self._settle(strategy, primary_seconds, max_age_seconds, window_start)

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
