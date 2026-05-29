"""Dispatcher workflow — spawns one PulseScanWorkflow per opted-in team."""

import json
import asyncio
import datetime as dt

import structlog
import posthoganalytics
from pydantic import BaseModel
from temporalio import activity, common, workflow

from posthog.models import Team
from posthog.models.pulse import PulseSubscription, PulseSubscriptionFrequency
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse import metrics
from posthog.temporal.ai.pulse.period import period_bounds, period_key
from posthog.temporal.ai.pulse.workflow import PulseScanInputs, PulseScanWorkflow
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)

# Max child PulseScans running concurrently across all teams.
DISPATCHER_CONCURRENCY = 10
PULSE_FEATURE_FLAG = "max-pulse"


class PulseScanDispatcherInputs(BaseModel):
    frequency: PulseSubscriptionFrequency = PulseSubscriptionFrequency.WEEKLY
    # Restrict to specific team IDs (debugging / testing). Empty means all opted-in teams.
    team_ids: list[int] | None = None


def _pulse_enabled_for_team(team: Team) -> bool:
    """Server-side flag gate, mirroring the API gate so disabled teams never get scanned."""
    return bool(
        posthoganalytics.feature_enabled(
            PULSE_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


@activity.defn
async def list_eligible_team_ids_activity(frequency: str, team_ids: list[int] | None) -> list[int]:
    @database_sync_to_async
    def _list() -> list[int]:
        # Cross-team read: the fail-closed manager must be bypassed explicitly.
        qs = PulseSubscription.objects.unscoped().filter(enabled=True, frequency=frequency)
        if team_ids:
            qs = qs.filter(team_id__in=team_ids)
        candidate_ids = list(qs.values_list("team_id", flat=True))
        if not candidate_ids:
            return []
        teams = Team.objects.filter(id__in=candidate_ids).only("id", "uuid", "organization_id")
        return [t.id for t in teams if _pulse_enabled_for_team(t)]

    eligible = await _list()
    metrics.increment_dispatch_outcome("eligible", count=len(eligible))
    return eligible


def build_child_workflow_id(team_id: int, now: dt.datetime, frequency: PulseSubscriptionFrequency | str) -> str:
    """Deterministic per-period child id so a re-dispatched scan dedupes to the same workflow run."""
    return f"pulse-scan-{team_id}-{period_key(now, frequency)}"


def build_scan_inputs(team_id: int, now: dt.datetime, frequency: PulseSubscriptionFrequency | str) -> PulseScanInputs:
    start, end = period_bounds(now, frequency)
    return PulseScanInputs(
        team_id=team_id,
        period_key=period_key(now, frequency),
        period_start=start.isoformat(),
        period_end=end.isoformat(),
    )


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
            args=[inputs.frequency.value, inputs.team_ids],
            start_to_close_timeout=dt.timedelta(seconds=60),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

        if not team_ids:
            return {"dispatched": 0, "total_eligible": 0}

        now = workflow.now()
        semaphore = asyncio.Semaphore(DISPATCHER_CONCURRENCY)

        async def _dispatch_one(team_id: int) -> bool:
            async with semaphore:
                try:
                    await workflow.execute_child_workflow(
                        PulseScanWorkflow.run,
                        build_scan_inputs(team_id, now, inputs.frequency),
                        id=build_child_workflow_id(team_id, now, inputs.frequency),
                        task_queue=workflow.info().task_queue,
                        retry_policy=common.RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(minutes=45),
                    )
                    metrics.increment_dispatch_outcome("dispatched")
                    return True
                except Exception as exc:
                    workflow.logger.exception("pulse_dispatch_child_failed", team_id=team_id, error=str(exc))
                    metrics.increment_dispatch_outcome("failed")
                    return False

        results = await asyncio.gather(*[_dispatch_one(tid) for tid in team_ids], return_exceptions=False)
        return {"dispatched": sum(1 for ok in results if ok), "total_eligible": len(team_ids)}
