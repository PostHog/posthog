from typing import Any, Optional
from posthoganalytics.client import Client
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)


class _PostHogClientActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        ph_client = Client(api_key="sTMFPsFhdP1Ssg", enable_exception_autocapture=True)

        try:
            activity_result = await super().execute_activity(input)
        except:
            raise
        finally:
            ph_client.flush()

        return activity_result


class _PostHogClientWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        ph_client = Client(api_key="sTMFPsFhdP1Ssg", enable_exception_autocapture=True)

        try:
            workflow_result = await super().execute_workflow(input)
        except:
            raise
        finally:
            ph_client.flush()

        return workflow_result


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
