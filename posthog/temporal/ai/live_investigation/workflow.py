"""Temporal workflow owning the lifecycle of a single LiveInvestigation.

Pattern mirrors `posthog_code_slack_mention.PostHogCodeSlackMentionWorkflow`:
parks on a `wait_condition` until events accumulate (signaled by the Celery
beat), the analyst forces analysis, the operator closes, or the deadline
expires. Then runs an analysis activity and always uninstalls the program.
"""

from __future__ import annotations

import json
from datetime import timedelta

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ActivityCancellationType

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai.live_investigation.activities import (
        analyze_live_investigation_activity,
        mark_investigation_cancelled_activity,
        uninstall_program_activity,
    )
    from posthog.temporal.ai.live_investigation.schemas import (
        AnalyzeInput,
        LiveInvestigationWorkflowInput,
        MarkCancelledInput,
        UninstallInput,
    )

logger = structlog.get_logger(__name__)

ANALYZE_ACTIVITY_TIMEOUT_SECONDS = 20 * 60
ANALYZE_ACTIVITY_HEARTBEAT_SECONDS = 5 * 60
UNINSTALL_ACTIVITY_TIMEOUT_SECONDS = 30
MARK_CANCELLED_ACTIVITY_TIMEOUT_SECONDS = 30
MAX_EXTENSION_SECONDS = 24 * 3600


@workflow.defn(name="live-investigation")
class LiveInvestigationWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._events_ready: bool = False
        self._force_analyze: bool = False
        self._closed: bool = False
        self._deadline_extensions_seconds: int = 0

    @workflow.signal
    async def events_ready(self) -> None:
        self._events_ready = True

    @workflow.signal
    async def extend(self, extra_seconds: int) -> None:
        self._deadline_extensions_seconds = min(
            self._deadline_extensions_seconds + extra_seconds,
            MAX_EXTENSION_SECONDS,
        )

    @workflow.signal
    async def analyze_now(self) -> None:
        self._force_analyze = True

    @workflow.signal
    async def close(self) -> None:
        self._closed = True

    @staticmethod
    def parse_inputs(inputs: list[str]) -> LiveInvestigationWorkflowInput:
        loaded = json.loads(inputs[0])
        return LiveInvestigationWorkflowInput(**loaded)

    @workflow.run
    async def run(self, input: LiveInvestigationWorkflowInput) -> None:
        try:
            try:
                await workflow.wait_condition(
                    lambda: self._events_ready or self._force_analyze or self._closed,
                    timeout=timedelta(
                        seconds=input.max_duration_seconds + self._deadline_extensions_seconds
                    ),
                )
            except TimeoutError:
                # Treated the same as events_ready=False — analyze with whatever
                # arrived. The followup agent will mark findings inconclusive if
                # there isn't enough signal.
                pass

            if self._closed:
                await workflow.execute_activity(
                    mark_investigation_cancelled_activity,
                    MarkCancelledInput(investigation_id=input.investigation_id),
                    start_to_close_timeout=timedelta(seconds=MARK_CANCELLED_ACTIVITY_TIMEOUT_SECONDS),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            await workflow.execute_activity(
                analyze_live_investigation_activity,
                AnalyzeInput(investigation_id=input.investigation_id),
                start_to_close_timeout=timedelta(seconds=ANALYZE_ACTIVITY_TIMEOUT_SECONDS),
                heartbeat_timeout=timedelta(seconds=ANALYZE_ACTIVITY_HEARTBEAT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        finally:
            # Always uninstall the program. ABANDON cancellation_type ensures that
            # if the workflow is cancelled externally, the uninstall activity still
            # runs to completion — uninstalling a live program is the entire point
            # of cleanup.
            await workflow.execute_activity(
                uninstall_program_activity,
                UninstallInput(program_id=input.program_id),
                start_to_close_timeout=timedelta(seconds=UNINSTALL_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
                cancellation_type=ActivityCancellationType.ABANDON,
            )
