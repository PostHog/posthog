from typing import Any

from django.conf import settings

from temporalio import workflow
from temporalio.worker import (
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloCompletedProperties, SloConfig, SloOutcome, SloStartedProperties
from posthog.temporal.common.errors import (
    MAX_ERROR_MESSAGE_CHARS,
    resolve_error_trace,
    resolve_exception_class,
    truncate_for_temporal_payload,
    unwrap_temporal_cause,
)


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
            # setdefault lets workflows pre-populate completion_properties to override any of these.
            slo.completion_properties.setdefault("error_type", resolve_exception_class(exc))
            slo.completion_properties.setdefault(
                "error_message",
                truncate_for_temporal_payload(str(unwrap_temporal_cause(exc) or exc), MAX_ERROR_MESSAGE_CHARS),
            )
            slo.completion_properties.setdefault("error_trace", resolve_error_trace(exc))
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
