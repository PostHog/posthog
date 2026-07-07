from dataclasses import is_dataclass
from typing import Any, Optional

import temporalio.exceptions
from opentelemetry import trace
from posthoganalytics import api_key, capture_exception
from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.common.interceptor import ALL_TASK_QUEUES
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.common.utils import is_transient_db_connection_error

logger = get_write_only_logger()


def _activity_will_retry(activity_info: "activity.Info") -> bool:
    """Whether the activity has retry attempts remaining after the current one.

    ``maximum_attempts`` of 0 means unlimited retries; ``None`` means the server didn't report
    the policy, in which case we assume more attempts may follow rather than treating this as final.
    """
    retry_policy = activity_info.retry_policy
    if retry_policy is None:
        return True
    maximum_attempts = retry_policy.maximum_attempts
    return maximum_attempts == 0 or activity_info.attempt < maximum_attempts


def _tag_team_id_on_current_span(input: ExecuteActivityInput | ExecuteWorkflowInput) -> None:
    """Tag the active span (the Temporal RunActivity/RunWorkflow span, when OTel tracing is
    enabled on the worker) with team_id read from the activity/workflow input.

    team_id is named consistently across PostHog's Temporal input dataclasses, so a reflective
    read covers nearly all of them without per-workflow opt-in. Best-effort: span bookkeeping
    must never break execution, and set_attribute is a non-IO no-op when the span isn't recording."""
    try:
        if not (len(input.args) == 1 and is_dataclass(input.args[0])):
            return
        team_id = getattr(input.args[0], "team_id", None)
        if not isinstance(team_id, int) or isinstance(team_id, bool):
            return
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("team_id", team_id)
    except Exception:
        pass


async def _add_inputs_to_capture_kwargs(
    capture_kwargs: dict[str, Any],
    input: ExecuteActivityInput | ExecuteWorkflowInput,
):
    try:
        if len(input.args) == 1 and is_dataclass(input.args[0]):
            if hasattr(input.args[0], "properties_to_log"):
                if "properties" not in capture_kwargs:
                    capture_kwargs["properties"] = {}
                capture_kwargs["properties"].update(input.args[0].properties_to_log)
            if hasattr(input.args[0], "user_distinct_id_to_log"):
                capture_kwargs["distinct_id"] = input.args[0].user_distinct_id_to_log
    except Exception as e:
        await logger.awarning(
            "Failed to add inputs to properties for class %s", type(input.args[0]).__name__, exc_info=e
        )
        capture_exception(e, **capture_kwargs)


class _PostHogClientActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        _tag_team_id_on_current_span(input)
        try:
            return await super().execute_activity(input)
        except Exception as e:
            # Cancellations (worker drain, activity timeout, workflow cancellation) are expected
            # control flow, not defects — re-raise without reporting them to error tracking.
            if temporalio.exceptions.is_cancelled_exception(e):
                raise
            activity_info = activity.info()
            # Transient pgbouncer/Postgres connection drops recover on a fresh connection and are
            # retried by the activity's retry policy. Don't report them as new error-tracking issues
            # while retries remain — a genuinely degraded DB still surfaces on the final attempt.
            if _activity_will_retry(activity_info) and is_transient_db_connection_error(e):
                raise
            capture_kwargs = {
                "properties": {
                    "temporal.execution_type": "activity",
                    "module": input.fn.__module__ + "." + input.fn.__qualname__,
                    "temporal.activity.attempt": activity_info.attempt,
                    "temporal.activity.id": activity_info.activity_id,
                    "temporal.activity.type": activity_info.activity_type,
                    "temporal.activity.task_queue": activity_info.task_queue,
                    "temporal.workflow.id": activity_info.workflow_id,
                    "temporal.workflow.namespace": activity_info.workflow_namespace,
                    "temporal.workflow.run_id": activity_info.workflow_run_id,
                    "temporal.workflow.type": activity_info.workflow_type,
                }
            }
            await _add_inputs_to_capture_kwargs(capture_kwargs, input)
            if api_key:
                try:
                    capture_exception(e, **capture_kwargs)  # type: ignore[arg-type]
                except Exception as capture_error:
                    await logger.awarning("Failed to capture exception", exc_info=capture_error)
            raise


class _PostHogClientWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        _tag_team_id_on_current_span(input)
        try:
            return await super().execute_workflow(input)
        except Exception as e:
            if isinstance(e, temporalio.exceptions.ActivityError):
                raise  # Already captured at the activity level
            if temporalio.exceptions.is_cancelled_exception(e):
                raise  # Expected cancellation (worker drain, timeout, cancel), not a defect
            try:
                workflow_info = workflow.info()
                capture_kwargs = {
                    "properties": {
                        "temporal.execution_type": "workflow",
                        "module": input.run_fn.__module__ + "." + input.run_fn.__qualname__,
                        "temporal.workflow.task_queue": workflow_info.task_queue,
                        "temporal.workflow.namespace": workflow_info.namespace,
                        "temporal.workflow.run_id": workflow_info.run_id,
                        "temporal.workflow.type": workflow_info.workflow_type,
                        "temporal.workflow.id": workflow_info.workflow_id,
                    }
                }
                await _add_inputs_to_capture_kwargs(capture_kwargs, input)
                if api_key and not workflow.unsafe.is_replaying():
                    with workflow.unsafe.sandbox_unrestricted():
                        try:
                            capture_exception(e, **capture_kwargs)  # type: ignore[arg-type]
                        except Exception as capture_error:
                            await logger.awarning("Failed to capture exception", exc_info=capture_error)
            except Exception:
                pass
            raise


class PostHogClientInterceptor(Interceptor):
    """PostHog Interceptor: reports workflow & activity exceptions to PostHog and tags the
    Temporal span of each execution with team_id (read reflectively from the input)."""

    task_queue = ALL_TASK_QUEUES

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        """Implementation of
        :py:meth:`temporalio.worker.Interceptor.intercept_activity`.
        """
        return _PostHogClientActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[type[WorkflowInboundInterceptor]]:
        return _PostHogClientWorkflowInterceptor
