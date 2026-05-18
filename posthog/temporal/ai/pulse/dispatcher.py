"""Dispatcher workflow — spawns one PulseScanWorkflow per opted-in team."""

import json
import asyncio
from datetime import timedelta

import structlog
from pydantic import BaseModel
from temporalio import activity, common, workflow

from posthog.models.pulse import PulseSubscriptionFrequency
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.workflow import PulseScanInputs, PulseScanWorkflow
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)

# Max child PulseScans running concurrently across all teams.
DISPATCHER_CONCURRENCY = 10


class PulseScanDispatcherInputs(BaseModel):
    frequency: PulseSubscriptionFrequency = PulseSubscriptionFrequency.WEEKLY
    # Restrict to specific team IDs (debugging / testing). Empty means all opted-in teams.
    team_ids: list[int] | None = None


@activity.defn
async def list_eligible_team_ids_activity(frequency: str, team_ids: list[int] | None) -> list[int]:
    from posthog.models.pulse import PulseSubscription

    @database_sync_to_async
    def _list() -> list[int]:
        qs = PulseSubscription.objects.filter(enabled=True, frequency=frequency)
        if team_ids:
            qs = qs.filter(team_id__in=team_ids)
        return list(qs.values_list("team_id", flat=True))

    return await _list()


@workflow.defn(name="pulse-scan-dispatcher")
class PulseScanDispatcherWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PulseScanDispatcherInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return PulseScanDispatcherInputs.model_validate(loaded)

    @workflow.run
    async def run(self, inputs: PulseScanDispatcherInputs) -> dict:
        team_ids = await workflow.execute_activity(
            list_eligible_team_ids_activity,
            args=[inputs.frequency, inputs.team_ids],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

        if not team_ids:
            return {"dispatched": 0}

        semaphore = asyncio.Semaphore(DISPATCHER_CONCURRENCY)

        async def _dispatch_one(team_id: int) -> bool:
            async with semaphore:
                try:
                    await workflow.execute_child_workflow(
                        PulseScanWorkflow.run,
                        PulseScanInputs(team_id=team_id),
                        id=f"pulse-scan-{team_id}-{workflow.now().isoformat()}",
                        task_queue=workflow.info().task_queue,
                        retry_policy=common.RetryPolicy(maximum_attempts=1),
                        execution_timeout=timedelta(minutes=45),
                    )
                    return True
                except Exception as exc:
                    workflow.logger.exception("pulse_dispatch_child_failed", team_id=team_id, error=str(exc))
                    return False

        results = await asyncio.gather(*[_dispatch_one(tid) for tid in team_ids], return_exceptions=False)
        return {"dispatched": sum(1 for ok in results if ok), "total_eligible": len(team_ids)}
