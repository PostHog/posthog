import json
from datetime import timedelta
from typing import Any, NotRequired, Required, TypedDict

from django.conf import settings

import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_errors import (
    application_error_details,
    get_evaluation_error_spec,
    is_terminal_user_error_result,
    status_reason_detail_for_terminal_user_error,
    terminal_user_error_result_from_application_error,
)
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io, extract_event_tools
from posthog.temporal.ai_observability.evaluation_hog import execute_hog_eval_activity, run_hog_eval
from posthog.temporal.ai_observability.evaluation_llm_judge import (
    DEFAULT_JUDGE_MODEL,
    LLM_JUDGE_RETRY_POLICY,
    BooleanEvalResult,
    BooleanWithNAEvalResult,
    ExecuteLLMJudgeInputs,
    build_system_prompt,
    execute_llm_judge_activity,
    get_output_type_config,
)
from posthog.temporal.ai_observability.evaluation_sentiment import execute_sentiment_eval_activity
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.evaluation_workflow_activities import (
    EmitEvaluationEventInputs,
    EmitInternalTelemetryInputs,
    RunEvaluationInputs,
    SendEvaluationDisabledEmailInputs,
    SendTrialUsageEmailInputs,
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    send_evaluation_disabled_email_activity,
    send_trial_usage_email_activity,
    update_key_state_activity,
)
from posthog.temporal.ai_observability.metrics import increment_errors
from posthog.temporal.common.base import PostHogWorkflow

from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.signals.backend.temporal.emit_eval_signal import (
    EmitEvalSignalInputs,
    EmitEvalSignalWorkflow,
    emit_eval_signal_activity,
)

__all__ = [
    "BooleanEvalResult",
    "BooleanWithNAEvalResult",
    "DEFAULT_JUDGE_MODEL",
    "EmitEvaluationEventInputs",
    "EmitInternalTelemetryInputs",
    "ExecuteLLMJudgeInputs",
    "EvaluationActivityResult",
    "RunEvaluationInputs",
    "RunEvaluationWorkflow",
    "SendEvaluationDisabledEmailInputs",
    "SendTrialUsageEmailInputs",
    "WorkflowResult",
    "build_system_prompt",
    "disable_evaluation_activity",
    "emit_evaluation_event_activity",
    "emit_internal_telemetry_activity",
    "execute_hog_eval_activity",
    "execute_llm_judge_activity",
    "execute_sentiment_eval_activity",
    "extract_event_io",
    "extract_event_tools",
    "fetch_evaluation_activity",
    "get_output_type_config",
    "handle_llm_judge_activity_error",
    "handle_terminal_user_error_result",
    "increment_trial_eval_count_activity",
    "increment_trial_usage_and_notify",
    "run_hog_eval",
    "send_evaluation_disabled_email_activity",
    "send_trial_usage_email_activity",
    "update_key_state_activity",
]


class WorkflowResult(TypedDict, total=False):
    """Result returned by `RunEvaluationWorkflow.run`."""

    evaluation_id: Required[str]
    evaluation_type: Required[str]
    skipped: Required[bool]
    verdict: NotRequired[bool | None]
    reasoning: NotRequired[str]
    is_byok: NotRequired[bool]
    skip_reason: NotRequired[str]
    message: NotRequired[str]


async def handle_llm_judge_activity_error(
    e: temporalio.exceptions.ActivityError, evaluation: dict[str, Any], evaluation_type: str
) -> WorkflowResult | None:
    """Workflow-side handling of terminal LLM judge errors, shared by the single-event and
    trace-level workflows. Must run inside a workflow context.

    For skippable terminal errors, disables the evaluation and sends notification emails where
    appropriate, then returns a skip WorkflowResult the caller should return as-is. For
    provider-key API errors, records the key state and returns None. Returns None for anything
    else — the caller must re-raise.
    """
    if not (isinstance(e.cause, ApplicationError) and e.cause.details):
        return None

    details = application_error_details(e.cause)
    error_type = details.get("error_type")

    terminal_result = terminal_user_error_result_from_application_error(
        e.cause,
        allows_na=(evaluation.get("output_config") or {}).get("allows_na", False),
    )
    if terminal_result is not None:
        return await handle_terminal_user_error_result(
            evaluation=evaluation,
            evaluation_type=evaluation_type,
            result=terminal_result,
        )

    if error_type == "parse_error":
        skip_result: WorkflowResult = {
            "verdict": None,
            "skipped": True,
            "skip_reason": error_type,
            "message": e.cause.message,
            "evaluation_id": evaluation["id"],
            "evaluation_type": evaluation_type,
        }
        return skip_result

    key_id = details.get("key_id")
    if key_id and error_type in ("auth_error", "permission_error", "quota_error", "rate_limit"):
        new_state = LLMProviderKey.State.INVALID if error_type == "auth_error" else LLMProviderKey.State.ERROR
        await temporalio.workflow.execute_activity(
            update_key_state_activity,
            args=[key_id, new_state, e.cause.message],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    return None


async def handle_terminal_user_error_result(
    *,
    evaluation: dict[str, Any],
    evaluation_type: str,
    result: EvaluationActivityResult,
) -> WorkflowResult:
    """Workflow-side handling of a terminal user error surfaced as an activity result, shared by
    the single-event and trace-level workflows. Must run inside a workflow context. Disables the
    evaluation where the error spec calls for it, records provider-key state, sends the
    appropriate notification email, and returns the skip WorkflowResult the caller should return.
    """
    skip_reason = result.get("skip_reason", "terminal_user_error")
    spec = get_evaluation_error_spec(
        str(skip_reason) if skip_reason else None,
        is_byok=bool(result.get("is_byok", False)),
    )
    status_reason = result.get("status_reason")
    disabled_evaluation = False
    if status_reason:
        reasoning = result.get("reasoning")
        status_reason_detail = (
            status_reason_detail_for_terminal_user_error(
                spec,
                reasoning if isinstance(reasoning, str) else None,
            )
            if spec
            else None
        )
        disabled_evaluation = await temporalio.workflow.execute_activity(
            disable_evaluation_activity,
            args=[evaluation["id"], evaluation["team_id"], status_reason, status_reason_detail],
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    key_id = result.get("key_id")
    provider_key_state = result.get("provider_key_state")
    if key_id and provider_key_state:
        await temporalio.workflow.execute_activity(
            update_key_state_activity,
            args=[str(key_id), provider_key_state, result["reasoning"]],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    if spec and spec.send_trial_usage_email and temporalio.workflow.patched("trial-usage-email"):
        try:
            await temporalio.workflow.execute_activity(
                send_trial_usage_email_activity,
                SendTrialUsageEmailInputs(team_id=evaluation["team_id"], threshold_pct=100),
                activity_id=f"send-trial-usage-email-100pct-{evaluation['team_id']}",
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            temporalio.workflow.logger.exception(
                "Failed to send trial exhausted email",
                team_id=evaluation["team_id"],
            )

    dedupe_disabled_email = temporalio.workflow.patched("eval-disabled-email-on-disable-transition")
    should_send_disabled_email = (
        spec is not None
        and spec.disables_evaluation
        and bool(status_reason)
        and (disabled_evaluation or not dedupe_disabled_email)
        and not spec.send_trial_usage_email
        and temporalio.workflow.patched("eval-disabled-email")
    )
    if should_send_disabled_email:
        assert spec is not None
        email_status_reason = str(status_reason)
        try:
            await temporalio.workflow.execute_activity(
                send_evaluation_disabled_email_activity,
                SendEvaluationDisabledEmailInputs(
                    team_id=evaluation["team_id"],
                    evaluation_id=evaluation["id"],
                    evaluation_name=evaluation.get("name", "Unknown evaluation"),
                    status_reason=email_status_reason,
                    human_readable_reason=spec.safe_message,
                    disabled_at=temporalio.workflow.now(),
                ),
                activity_id=f"send-eval-disabled-email-{evaluation['id']}-{email_status_reason}",
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            temporalio.workflow.logger.exception(
                "Failed to send evaluation disabled email",
                evaluation_id=evaluation["id"],
                team_id=evaluation["team_id"],
            )

    workflow_result: WorkflowResult = {
        "verdict": None,
        "skipped": True,
        "skip_reason": skip_reason,
        "message": result["reasoning"],
        "evaluation_id": evaluation["id"],
        "evaluation_type": evaluation_type,
    }
    return workflow_result


async def increment_trial_usage_and_notify(evaluation: dict[str, Any]) -> None:
    """Increment the team's trial eval counter and send threshold emails. Must run inside a
    workflow context. Shared by the single-event and trace-level workflows; callers gate on
    `is_byok` / `skipped` so only PostHog-key LLM judge runs consume quota.
    """
    threshold_pct = await temporalio.workflow.execute_activity(
        increment_trial_eval_count_activity,
        evaluation["team_id"],
        activity_id=f"increment-trial-{evaluation['id']}",
        schedule_to_close_timeout=timedelta(seconds=10),
        retry_policy=RetryPolicy(maximum_attempts=2),
    )

    if threshold_pct is not None and temporalio.workflow.patched("trial-usage-email"):
        try:
            await temporalio.workflow.execute_activity(
                send_trial_usage_email_activity,
                SendTrialUsageEmailInputs(team_id=evaluation["team_id"], threshold_pct=threshold_pct),
                activity_id=f"send-trial-usage-email-{threshold_pct}pct-{evaluation['team_id']}",
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            temporalio.workflow.logger.exception(
                "Failed to send trial usage email",
                team_id=evaluation["team_id"],
                threshold_pct=threshold_pct,
            )


@temporalio.workflow.defn(name="run-evaluation")
class RunEvaluationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunEvaluationInputs:
        return RunEvaluationInputs(
            evaluation_id=inputs[0],
            event_data=json.loads(inputs[1]),
        )

    @temporalio.workflow.run
    async def run(self, inputs: RunEvaluationInputs) -> WorkflowResult:
        start_time = temporalio.workflow.now()
        evaluation = await temporalio.workflow.execute_activity(
            fetch_evaluation_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        evaluation_type = evaluation.get("evaluation_type", "llm_judge")

        if evaluation_type == "hog":
            result = await temporalio.workflow.execute_activity(
                execute_hog_eval_activity,
                args=[evaluation, inputs.event_data],
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        elif evaluation_type == "sentiment":
            result = await temporalio.workflow.execute_activity(
                execute_sentiment_eval_activity,
                args=[evaluation, inputs.event_data],
                schedule_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        elif evaluation_type == "llm_judge":
            try:
                result = await temporalio.workflow.execute_activity(
                    execute_llm_judge_activity,
                    ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=inputs.event_data),
                    schedule_to_close_timeout=timedelta(minutes=6),
                    retry_policy=LLM_JUDGE_RETRY_POLICY,
                )
            except temporalio.exceptions.ActivityError as e:
                handled = await handle_llm_judge_activity_error(e, evaluation, evaluation_type)
                if handled is not None:
                    return handled
                raise

            if not result.get("is_byok") and not result.get("skipped"):
                await increment_trial_usage_and_notify(evaluation)
        else:
            raise ApplicationError(
                f"Unsupported evaluation type: {evaluation_type}",
                non_retryable=True,
            )

        if is_terminal_user_error_result(result):
            return await handle_terminal_user_error_result(
                evaluation=evaluation,
                evaluation_type=evaluation_type,
                result=result,
            )

        try:
            await temporalio.workflow.execute_activity(
                emit_evaluation_event_activity,
                EmitEvaluationEventInputs(
                    evaluation=evaluation,
                    event_data=inputs.event_data,
                    result=result,
                    start_time=start_time,
                ),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            increment_errors("emit_evaluation_event_failed", provider=result.get("provider"))
            raise

        if evaluation_type == "llm_judge" and not result.get("skipped"):
            await temporalio.workflow.execute_activity(
                emit_internal_telemetry_activity,
                EmitInternalTelemetryInputs(
                    evaluation=evaluation,
                    team_id=evaluation["team_id"],
                    result=result,
                ),
                schedule_to_close_timeout=timedelta(seconds=30),
            )

        if evaluation_type == "llm_judge" and result.get("verdict") is True and result.get("reasoning"):
            event_uuid = inputs.event_data.get("uuid", "")
            properties = inputs.event_data.get("properties", {})
            if isinstance(properties, str):
                properties = json.loads(properties)

            signal_inputs = EmitEvalSignalInputs(
                team_id=evaluation["team_id"],
                evaluation_id=evaluation["id"],
                evaluation_name=evaluation.get("name", "Unknown evaluation"),
                evaluation_prompt=(evaluation.get("evaluation_config") or {}).get("prompt", ""),
                event_uuid=event_uuid,
                event_type=inputs.event_data.get("event", ""),
                trace_id=properties.get("$ai_trace_id", ""),
                reasoning=result.get("reasoning", ""),
                model=result.get("model", ""),
                provider=result.get("provider", ""),
            )

            if temporalio.workflow.patched("emit-eval-signal-v2"):
                try:
                    await temporalio.workflow.start_child_workflow(
                        EmitEvalSignalWorkflow.run,
                        signal_inputs,
                        id=f"emit-eval-signal-{evaluation['team_id']}-{evaluation['id']}-{event_uuid}",
                        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                        parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                        execution_timeout=timedelta(minutes=5),
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "Failed to start eval signal workflow",
                        evaluation_id=evaluation["id"],
                        team_id=evaluation["team_id"],
                    )
            elif temporalio.workflow.patched("emit-eval-signal-v1"):
                try:
                    await temporalio.workflow.execute_activity(
                        emit_eval_signal_activity,
                        signal_inputs,
                        schedule_to_close_timeout=timedelta(seconds=120),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "Failed to emit eval signal",
                        evaluation_id=evaluation["id"],
                        team_id=evaluation["team_id"],
                    )

        workflow_result: WorkflowResult = {
            "reasoning": result["reasoning"],
            "evaluation_id": evaluation["id"],
            "evaluation_type": evaluation_type,
            "is_byok": result.get("is_byok", False),
            "skipped": result.get("skipped", False),
        }
        if "verdict" in result:
            workflow_result["verdict"] = result["verdict"]
        if result.get("skipped"):
            skip_reason = result.get("skip_reason")
            if skip_reason is not None:
                workflow_result["skip_reason"] = skip_reason
        return workflow_result
