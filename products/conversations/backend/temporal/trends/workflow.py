from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import structlog

    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.temporal.trends.detection import run_detection

logger = structlog.get_logger(__name__)


@dataclass
class TrendsAnalysisInput:
    team_id: int


@dataclass
class TrendsAnalysisOutput:
    incidents_fired: int
    incidents_resolved: int
    rules_evaluated: int


@activity.defn
async def ticket_trends_detect_activity(input: TrendsAnalysisInput) -> TrendsAnalysisOutput:
    """Run Tier-1 spike detection for one team: built-in series + alert rules."""
    async with Heartbeater():
        stats = await database_sync_to_async(run_detection, thread_sensitive=False)(input.team_id)
    logger.info(
        "ticket_trends: detection complete",
        team_id=input.team_id,
        incidents_fired=stats.incidents_fired,
        incidents_resolved=stats.incidents_resolved,
        rules_evaluated=stats.rules_evaluated,
    )
    return TrendsAnalysisOutput(
        incidents_fired=stats.incidents_fired,
        incidents_resolved=stats.incidents_resolved,
        rules_evaluated=stats.rules_evaluated,
    )


@workflow.defn(name="ticket-trends-analysis")
class TicketTrendsAnalysisWorkflow:
    """Per-team ticket trends analysis. Phase 1 is detection only; the AI
    clustering activities slot in here later as additional steps."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrendsAnalysisInput:
        loaded = json.loads(inputs[0])
        return TrendsAnalysisInput(**loaded)

    @workflow.run
    async def run(self, input: TrendsAnalysisInput) -> TrendsAnalysisOutput:
        return await workflow.execute_activity(
            ticket_trends_detect_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
