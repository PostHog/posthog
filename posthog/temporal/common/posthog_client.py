from dataclasses import is_dataclass
from typing import Any, Optional

import django.db

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


# Connection-level database failures (server closed the connection, connection reset,
# statement-timeout kill, deadlock) are transient infra blips, not defects. Temporal's activity
# retry policy recovers from them, so reporting each retried attempt to error tracking just spawns
# noise that resolves itself. django.db.Error wraps the underlying driver exceptions, so this
# catches both psycopg-raised and Django-raised variants.
_TRANSIENT_DB_EXCEPTIONS = (django.db.OperationalError, django.db.InterfaceError)


def _is_retriable_infra_exception(e: BaseException) -> bool:
    """Whether ``e`` (or anything in its cause chain) is a transient DB connection failure."""
    seen: set[int] = set()
    current: BaseException | None = e
    while current is not None and id(current) not in seen:
        if isinstance(current, _TRANSIENT_DB_EXCEPTIONS):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _activity_has_retries_remaining(activity_info: "activity.Info") -> bool:
    """Whether Temporal will schedule another attempt of this activity after the current one fails.

    ``maximum_attempts`` of 0 (or an unset policy) means unlimited retries, so there is always
    another attempt coming."""
    retry_policy = activity_info.retry_policy
    if retry_policy is None or not retry_policy.maximum_attempts:
        return True
    return activity_info.attempt < retry_policy.maximum_attempts


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
            # Transient DB connection blips are recovered by Temporal's retry policy. Don't report
            # them while retries remain — only surface one if it exhausts every attempt (a real,
            # persistent problem), so a self-healing retry doesn't spawn an error-tracking issue.
            if _is_retriable_infra_exception(e) and _activity_has_retries_remaining(activity_info):
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
