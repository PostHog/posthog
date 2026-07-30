"""Temporal interceptor that emits FinOps usage meters on activity/workflow completion.

Runs on ALL task queues when TEMPORAL_FINOPS_USAGE_METERS_ENABLED is true. Each
activity execution produces one meter with ``billable_unit=actions`` (Temporal Cloud's
billing unit) and the wall-clock duration. Workflow completions are also metered for
the workflow-start action count.

Fail-safe: metering errors are captured, never raised — the interceptor must never
break workflow or activity execution.
"""

from __future__ import annotations

import time
from dataclasses import is_dataclass
from typing import Any

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.common.finops_product_map import resolve_product
from posthog.temporal.common.finops_usage_meter import FinopsUsageMeter, FinopsUsageMeterInput
from posthog.temporal.common.interceptor import ALL_TASK_QUEUES


def _extract_team_id(input: ExecuteActivityInput | ExecuteWorkflowInput) -> int:
    """Reflectively read team_id from the first input arg, matching PostHogClientInterceptor."""
    try:
        if len(input.args) == 1 and is_dataclass(input.args[0]):
            team_id = getattr(input.args[0], "team_id", None)
            if isinstance(team_id, int) and not isinstance(team_id, bool):
                return team_id
    except Exception:
        pass
    return 0


class _FinopsActivityInboundInterceptor(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, meter: FinopsUsageMeter) -> None:
        super().__init__(next)
        self._meter = meter

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        start = time.monotonic()
        try:
            return await super().execute_activity(input)
        finally:
            try:
                info = activity.info()
                duration_ms = (time.monotonic() - start) * 1000
                self._meter.queue(
                    FinopsUsageMeterInput(
                        product=resolve_product(info.task_queue),
                        billable_unit="actions",
                        quantity=1,
                        team_id=_extract_team_id(input),
                        system="temporal",
                        workload=info.activity_type,
                        resource_id=info.task_queue,
                        duration_ms=duration_ms,
                    )
                )
                self._meter.flush()
            except Exception:
                pass


class _FinopsWorkflowInboundInterceptor(WorkflowInboundInterceptor):
    def __init__(self, next: WorkflowInboundInterceptor, meter: FinopsUsageMeter) -> None:
        super().__init__(next)
        self._meter = meter

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        start_time = workflow.time()
        try:
            return await self.next.execute_workflow(input)
        finally:
            if not workflow.unsafe.is_replaying():
                try:
                    info = workflow.info()
                    duration_ms = (workflow.time() - start_time) * 1000
                    with workflow.unsafe.sandbox_unrestricted():
                        self._meter.queue(
                            FinopsUsageMeterInput(
                                product=resolve_product(info.task_queue),
                                billable_unit="actions",
                                quantity=1,
                                team_id=_extract_team_id(input),
                                system="temporal",
                                workload=info.workflow_type,
                                resource_id=info.task_queue,
                                duration_ms=duration_ms,
                            )
                        )
                        self._meter.flush()
                except Exception:
                    pass


class FinopsUsageMeterInterceptor(Interceptor):
    """Emits FinOps usage meters for every Temporal activity and workflow execution."""

    task_queue = ALL_TASK_QUEUES

    def __init__(self) -> None:
        from django.conf import settings

        self._meter = FinopsUsageMeter(enabled=settings.TEMPORAL_FINOPS_USAGE_METERS_ENABLED)

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _FinopsActivityInboundInterceptor(super().intercept_activity(next), self._meter)

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        meter = self._meter

        class _BoundFinopsWorkflowInterceptor(_FinopsWorkflowInboundInterceptor):
            def __init__(self, next: WorkflowInboundInterceptor) -> None:
                super().__init__(next, meter)

        return _BoundFinopsWorkflowInterceptor
