from datetime import UTC, datetime, timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from .activities import list_effectiveness_teams, measure_effectiveness
    from .types import EffectivenessInput, MeasureTeamInput

EFFECTIVENESS_WORKFLOW_NAME = "data-catalog-effectiveness"

# A step that fails partway has already spent its model calls, so it gets one retry, not three.
_RETRY_POLICY = common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1))
_MEASURE_TIMEOUT = timedelta(hours=2)
# The longest quiet stretch is one telemetry query between heartbeats.
_HEARTBEAT_TIMEOUT = timedelta(minutes=20)


@frozen
class MeasuredWindow:
    start: datetime
    end: datetime


def previous_full_days(now: datetime, days: int) -> MeasuredWindow:
    """Whole UTC days that end at today's midnight, so that weekly runs neither overlap nor leave a gap."""
    end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return MeasuredWindow(start=end - timedelta(days=days), end=end)


@workflow.defn(name=EFFECTIVENESS_WORKFLOW_NAME)
class DataCatalogEffectivenessWorkflow(PostHogWorkflow):
    """One team at a time. A team that fails does not stop the others."""

    inputs_cls = EffectivenessInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: EffectivenessInput | None = None) -> dict[str, int]:
        input = input or EffectivenessInput()
        team_ids = input.team_ids
        if team_ids is None:
            team_ids = await workflow.execute_activity(
                list_effectiveness_teams, start_to_close_timeout=timedelta(minutes=5)
            )
        window = previous_full_days(workflow.now(), input.window_days)

        measured = skipped = failed = 0
        for team_id in team_ids:
            try:
                result = await workflow.execute_activity(
                    measure_effectiveness,
                    MeasureTeamInput(
                        team_id=team_id,
                        window_start=window.start,
                        window_end=window.end,
                        telemetry_team_id=input.telemetry_team_id,
                    ),
                    start_to_close_timeout=_MEASURE_TIMEOUT,
                    # A dead worker shows as missing heartbeats, so the retry starts long before the two-hour limit.
                    heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )
            except ActivityError:
                failed += 1
                continue
            if result.skipped:
                skipped += 1
            else:
                measured += 1
        return {"teams": len(team_ids), "measured": measured, "skipped": skipped, "failed": failed}
