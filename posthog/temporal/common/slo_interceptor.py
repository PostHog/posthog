import traceback
from typing import Any

from django.conf import settings

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.worker import (
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloCompletedProperties, SloConfig, SloOutcome, SloStartedProperties


def _unwrap_temporal_cause(exc: BaseException) -> BaseException:
    """Unwrap Temporal's ``ActivityError → ApplicationError`` chain to the original cause.

    When an activity raises, the Temporal SDK surfaces it on the workflow side
    as ``ActivityError(cause=ApplicationError(...))``. This helper peels off
    that wrapper so callers can inspect the real failure.
    """
    if isinstance(exc, ActivityError) and isinstance(exc.cause, ApplicationError):
        return exc.cause
    return exc


def resolve_exception_class(exc: BaseException) -> str:
    """Return the original exception class name, unwrapping Temporal's wrappers.

    Use this from a workflow's own exception handler when you need to inspect
    the failure *before* re-raising — e.g., to reclassify user-query errors as
    a non-breach outcome before the SLO interceptor records the completion.
    """
    cause = _unwrap_temporal_cause(exc)
    return getattr(cause, "type", None) or type(cause).__name__


def _extract_error_trace(exc: BaseException, cause: BaseException) -> str:
    """Return the best-available stack trace for a failed workflow.

    Prefers the activity-side traceback that the activity wrapper stashes in
    ``ApplicationError.details[0]`` (captured at the site of the real failure),
    and falls back to a truncated workflow-side traceback otherwise.
    """
    if isinstance(cause, ApplicationError) and cause.details and isinstance(cause.details[0], str):
        return cause.details[0]
    return "\n".join(traceback.format_exception(exc)[:5])


class _SloWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        slo: SloConfig | None = getattr(input.args[0], "slo", None) if input.args else None
        if slo is None:
            return await self.next.execute_workflow(input)

        # Attach workflow identity for debugging and query-level deduplication.
        info = workflow.info()
        workflow_context = {
            "correlation_id": info.run_id,
            "workflow_id": info.workflow_id,
            "workflow_type": info.workflow_type,
        }

        # Guard against duplicate events during Temporal workflow replay. When a
        # worker crashes and recovers, Temporal re-executes the workflow from the
        # beginning to rebuild state — without this guard, every replay would
        # re-emit SLO events and double-count Prometheus metrics.
        if not workflow.unsafe.is_replaying():
            with workflow.unsafe.sandbox_unrestricted():
                emit_slo_started(
                    distinct_id=slo.distinct_id,
                    properties=SloStartedProperties(
                        operation=slo.operation,
                        area=slo.area,
                        team_id=slo.team_id,
                        resource_id=slo.resource_id,
                    ),
                    extra_properties={**workflow_context, **(slo.start_properties or {})},
                )

        start_time = workflow.time()
        outcome = SloOutcome.SUCCESS
        try:
            result = await self.next.execute_workflow(input)
            outcome = slo.outcome if slo.outcome is not None else SloOutcome.SUCCESS
            return result
        except BaseException as exc:
            outcome = slo.outcome if slo.outcome is not None else SloOutcome.FAILURE
            # Temporal wraps activity errors as ActivityError → ApplicationError;
            # unwrap to get the original exception type, message, and trace.
            # Workflows can override any of these by pre-populating completion_properties
            # before re-raising (setdefault leaves existing values untouched).
            cause = _unwrap_temporal_cause(exc)
            slo.completion_properties.setdefault("error_type", getattr(cause, "type", None) or type(cause).__name__)
            slo.completion_properties.setdefault("error_message", str(cause))
            slo.completion_properties.setdefault("error_trace", _extract_error_trace(exc, cause))
            raise
        finally:
            duration_ms = (workflow.time() - start_time) * 1000
            if not workflow.unsafe.is_replaying():
                with workflow.unsafe.sandbox_unrestricted():
                    emit_slo_completed(
                        distinct_id=slo.distinct_id,
                        properties=SloCompletedProperties(
                            operation=slo.operation,
                            area=slo.area,
                            team_id=slo.team_id,
                            outcome=outcome,
                            resource_id=slo.resource_id,
                            duration_ms=duration_ms,
                        ),
                        extra_properties={**workflow_context, **(slo.completion_properties or {})},
                    )


class SloInterceptor(Interceptor):
    """Emits SLO started/completed events for opted-in workflows.

    Workflows opt in by adding ``slo: SloConfig | None = None`` to their input
    dataclass. See ``SloConfig`` for field documentation.
    """

    task_queue = settings.ANALYTICS_PLATFORM_TASK_QUEUE

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _SloWorkflowInterceptor
