from dataclasses import is_dataclass
from typing import Any, Optional, Union

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

with workflow.unsafe.imports_passed_through():
    from sentry_sdk import Hub, capture_exception, set_context, set_tag


def _set_common_workflow_tags(info: Union[workflow.Info, activity.Info]):
    set_tag("temporal.workflow.type", info.workflow_type)
    set_tag("temporal.workflow.id", info.workflow_id)


class _SentryActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        # https://docs.sentry.io/platforms/python/troubleshooting/#addressing-concurrency-issues
        with Hub(Hub.current):
            set_tag("temporal.execution_type", "activity")
            set_tag("module", input.fn.__module__ + "." + input.fn.__qualname__)

            activity_info = activity.info()
            _set_common_workflow_tags(activity_info)
            set_tag("temporal.activity.id", activity_info.activity_id)
            set_tag("temporal.activity.type", activity_info.activity_type)
            set_tag("temporal.activity.task_queue", activity_info.task_queue)
            set_tag("temporal.workflow.namespace", activity_info.workflow_namespace)
            set_tag("temporal.workflow.run_id", activity_info.workflow_run_id)
            try:
                return await super().execute_activity(input)
            except Exception:
                if len(input.args) == 1 and is_dataclass(input.args[0]):
                    team_id = getattr(input.args[0], "team_id", None)
                    if team_id:
                        set_tag("team_id", team_id)
                set_context("temporal.activity.info", activity.info().__dict__)
                capture_exception()
                raise


class _SentryWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        # https://docs.sentry.io/platforms/python/troubleshooting/#addressing-concurrency-issues
        with Hub(Hub.current):
            set_tag("temporal.execution_type", "workflow")
            set_tag("module", input.run_fn.__module__ + "." + input.run_fn.__qualname__)
            workflow_info = workflow.info()
            _set_common_workflow_tags(workflow_info)
            set_tag("temporal.workflow.task_queue", workflow_info.task_queue)
            set_tag("temporal.workflow.namespace", workflow_info.namespace)
            set_tag("temporal.workflow.run_id", workflow_info.run_id)
            try:
                return await super().execute_workflow(input)
            except Exception:
                if len(input.args) == 1 and is_dataclass(input.args[0]):
                    team_id = getattr(input.args[0], "team_id", None)
                    if team_id:
                        set_tag("team_id", team_id)
                set_context("temporal.workflow.info", workflow.info().__dict__)

                if not workflow.unsafe.is_replaying():
                    with workflow.unsafe.sandbox_unrestricted():
                        capture_exception()
                raise


class SentryInterceptor(Interceptor):
    """Temporal Interceptor class which will report workflow & activity exceptions to Sentry"""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        """Implementation of
        :py:meth:`temporalio.worker.Interceptor.intercept_activity`.
        """
        return _SentryActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[type[WorkflowInboundInterceptor]]:
        return _SentryWorkflowInterceptor
