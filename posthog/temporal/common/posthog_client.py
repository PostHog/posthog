from dataclasses import is_dataclass
from typing import Any, Optional

import temporalio.exceptions
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

from products.exports.backend.tasks.failure_handler import USER_QUERY_ERROR_NAMES

logger = get_write_only_logger()


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


def _exception_type_names(exception: Exception) -> set[str]:
    type_names = {type(exception).__name__}
    current_exception: Exception | None = exception
    seen_exception_ids: set[int] = set()

    while current_exception is not None and id(current_exception) not in seen_exception_ids:
        seen_exception_ids.add(id(current_exception))
        exception_type = getattr(current_exception, "type", None)
        if isinstance(exception_type, str):
            type_names.add(exception_type)

        cause = current_exception.__cause__
        if not isinstance(cause, Exception):
            break

        type_names.add(type(cause).__name__)
        current_exception = cause

    return type_names


def _is_user_query_error(exception: Exception) -> bool:
    return not USER_QUERY_ERROR_NAMES.isdisjoint(_exception_type_names(exception))


class _PostHogClientActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        try:
            return await super().execute_activity(input)
        except Exception as e:
            if _is_user_query_error(e):
                raise

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
            if api_key:
                try:
                    capture_exception(e, **capture_kwargs)  # type: ignore[arg-type]
                except Exception as capture_error:
                    await logger.awarning("Failed to capture exception", exc_info=capture_error)
            raise


class _PostHogClientWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
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
    """PostHog Interceptor class which will report workflow & activity exceptions to PostHog"""

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
