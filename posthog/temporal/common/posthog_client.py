from dataclasses import is_dataclass
from typing import Any, Literal, Optional

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

from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger()


async def _add_inputs_to_properties(
    properties: dict[str, Any],
    input: ExecuteActivityInput | ExecuteWorkflowInput,
    execution_type: Literal["activity", "workflow"],
):
    try:
        if len(input.args) == 1 and is_dataclass(input.args[0]) and hasattr(input.args[0], "properties_to_log"):
            properties.update(input.args[0].properties_to_log)
    except Exception as e:
        await logger.awarning(
            "Failed to add inputs to properties for class %s", type(input.args[0]).__name__, exc_info=e
        )
        capture_exception(e, properties=properties)


class _PostHogClientActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        try:
            return await super().execute_activity(input)
        except Exception as e:
            activity_info = activity.info()
            properties = {
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
            await _add_inputs_to_properties(properties, input, "activity")
            if api_key:
                try:
                    capture_exception(e, properties=properties)
                except Exception as capture_error:
                    await logger.awarning("Failed to capture exception", exc_info=capture_error)
            raise


class _PostHogClientWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        try:
            return await super().execute_workflow(input)
        except Exception as e:
            # we don't want to capture cancelled errors
            if isinstance(e, temporalio.exceptions.ActivityError) and isinstance(
                e.cause, temporalio.exceptions.CancelledError
            ):
                raise
            workflow_info = workflow.info()
            properties = {
                "temporal.execution_type": "workflow",
                "module": input.run_fn.__module__ + "." + input.run_fn.__qualname__,
                "temporal.workflow.task_queue": workflow_info.task_queue,
                "temporal.workflow.namespace": workflow_info.namespace,
                "temporal.workflow.run_id": workflow_info.run_id,
                "temporal.workflow.type": workflow_info.workflow_type,
                "temporal.workflow.id": workflow_info.workflow_id,
            }
            await _add_inputs_to_properties(properties, input, "workflow")
            if api_key and not workflow.unsafe.is_replaying():
                with workflow.unsafe.sandbox_unrestricted():
                    try:
                        capture_exception(e, properties=properties)
                    except Exception as capture_error:
                        await logger.awarning("Failed to capture exception", exc_info=capture_error)
            raise


class PostHogClientInterceptor(Interceptor):
    """PostHog Interceptor class which will report workflow & activity exceptions to PostHog"""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        """Implementation of
        :py:meth:`temporalio.worker.Interceptor.intercept_activity`.
        """
        return _PostHogClientActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[type[WorkflowInboundInterceptor]]:
        return _PostHogClientWorkflowInterceptor
