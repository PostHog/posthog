import json
from datetime import timedelta
from typing import NotRequired, Required, TypedDict

from django.conf import settings

import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

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
    "increment_trial_eval_count_activity",
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
                if isinstance(e.cause, ApplicationError) and e.cause.details:
                    details = e.cause.details[0]
                    error_type = details.get("error_type")

                    if error_type in (
                        "trial_limit_reached",
                        "key_invalid",
                        "parse_error",
                        "model_not_allowed",
                        "no_default_model",
                    ):
                        if error_type in ("trial_limit_reached", "model_not_allowed", "no_default_model"):
                            await temporalio.workflow.execute_activity(
                                disable_evaluation_activity,
                                args=[evaluation["id"], evaluation["team_id"], error_type],
                                schedule_to_close_timeout=timedelta(seconds=30),
                                retry_policy=RetryPolicy(maximum_attempts=2),
                            )
                            if error_type == "trial_limit_reached":
                                if temporalio.workflow.patched("trial-usage-email"):
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
                            elif error_type == "model_not_allowed":
                                if temporalio.workflow.patched("eval-disabled-email"):
                                    model = details.get("model", "the selected model")
                                    try:
                                        await temporalio.workflow.execute_activity(
                                            send_evaluation_disabled_email_activity,
                                            SendEvaluationDisabledEmailInputs(
                                                team_id=evaluation["team_id"],
                                                evaluation_id=evaluation["id"],
                                                evaluation_name=evaluation.get("name", "Unknown evaluation"),
                                                status_reason="model_not_allowed",
                                                human_readable_reason=(
                                                    f"The model '{model}' isn't available on the trial plan."
                                                ),
                                            ),
                                            activity_id=(
                                                f"send-eval-disabled-email-{evaluation['id']}-model_not_allowed"
                                            ),
                                            schedule_to_close_timeout=timedelta(seconds=30),
                                            retry_policy=RetryPolicy(maximum_attempts=2),
                                        )
                                    except Exception:
                                        temporalio.workflow.logger.exception(
                                            "Failed to send evaluation disabled email",
                                            evaluation_id=evaluation["id"],
                                            team_id=evaluation["team_id"],
                                        )
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
                        new_state = (
                            LLMProviderKey.State.INVALID if error_type == "auth_error" else LLMProviderKey.State.ERROR
                        )
                        await temporalio.workflow.execute_activity(
                            update_key_state_activity,
                            args=[key_id, new_state, e.cause.message],
                            schedule_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=2),
                        )
                raise

            if not result.get("is_byok") and not result.get("skipped"):
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
        else:
            raise ApplicationError(
                f"Unsupported evaluation type: {evaluation_type}",
                non_retryable=True,
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
