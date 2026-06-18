from dataclasses import is_dataclass
from typing import Any, Optional, TypeVar

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

logger = get_write_only_logger()

# Exceptions carrying this attribute (set to True) are only reported to error tracking on the
# final Temporal retry attempt. Lets an activity silence transient upstream failures (e.g. a 5xx)
# that the retry policy is expected to absorb, while still surfacing genuinely terminal failures.
_CAPTURE_ONLY_ON_FINAL_ATTEMPT_ATTR = "_posthog_capture_only_on_final_attempt"

_ExcT = TypeVar("_ExcT", bound=BaseException)


def capture_only_on_final_attempt(exc: _ExcT) -> _ExcT:
    """Mark an exception so the PostHog Temporal interceptor skips error-tracking capture on
    non-final activity attempts. Use for transient errors the retry policy is expected to absorb.
    Returns the same exception so callers can ``raise capture_only_on_final_attempt(e)``."""
    setattr(exc, _CAPTURE_ONLY_ON_FINAL_ATTEMPT_ATTR, True)
    return exc


def _is_final_activity_attempt(activity_info: activity.Info) -> bool:
    retry_policy = activity_info.retry_policy
    max_attempts = retry_policy.maximum_attempts if retry_policy else 0
    # maximum_attempts <= 0 means unlimited retries — there is no final attempt to defer to, so
    # capture rather than risk swallowing the error forever.
    if max_attempts <= 0:
        return True
    return activity_info.attempt >= max_attempts


def _should_capture_activity_exception(e: BaseException, activity_info: activity.Info) -> bool:
    if not getattr(e, _CAPTURE_ONLY_ON_FINAL_ATTEMPT_ATTR, False):
        return True
    return _is_final_activity_attempt(activity_info)


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
            activity_info = activity.info()
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
            if api_key and _should_capture_activity_exception(e, activity_info):
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
