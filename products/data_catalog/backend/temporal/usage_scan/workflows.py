from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from ...facade.enums import UsageSection
    from ...logic.usage_scan import SCAN_WORKFLOW_NAME, scan_workflow_id
    from .activities import (
        collect_metric_runs,
        collect_topics,
        create_snapshot,
        detect_adjusted_runs,
        finalize_snapshot,
        find_uncovered,
        list_teams_due,
    )
    from .types import (
        CreateSnapshotInput,
        FailedStep,
        FinalizeSnapshotInput,
        ScanStepInput,
        UsageScanInput,
        UsageScheduleInput,
    )

SCHEDULE_WORKFLOW_NAME = "data-catalog-usage-schedule"

# An LLM step that fails partway has already spent its judge calls, so it gets one retry, not three.
_STEP_RETRY_POLICY = common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1))
_SHORT_STEP = timedelta(minutes=15)
_LONG_STEP = timedelta(hours=1)

# In run order, because topics read the adjusted runs.
_STEPS = (
    (UsageSection.METRIC_RUNS, collect_metric_runs, _SHORT_STEP),
    (UsageSection.ADJUSTED_RUNS, detect_adjusted_runs, _LONG_STEP),
    (UsageSection.TOPICS, collect_topics, _SHORT_STEP),
    (UsageSection.UNCOVERED, find_uncovered, _LONG_STEP),
)


@workflow.defn(name=SCAN_WORKFLOW_NAME)
class DataCatalogUsageScanWorkflow(PostHogWorkflow):
    """One team's scan. A failed step leaves its section empty, and the later steps still run.
    The scan fails only when every step fails."""

    inputs_cls = UsageScanInput

    @workflow.run
    async def run(self, input: UsageScanInput) -> dict[str, int]:
        step_input = ScanStepInput(
            team_id=input.team_id, snapshot_id=input.snapshot_id, telemetry_team_id=input.telemetry_team_id
        )
        rows: dict[str, int] = {}
        failures: list[FailedStep] = []
        for section, step, timeout in _STEPS:
            try:
                written = await workflow.execute_activity(
                    step, step_input, start_to_close_timeout=timeout, retry_policy=_STEP_RETRY_POLICY
                )
            except ActivityError as error:
                failures.append(FailedStep(section=section.value, reason=_reason(error)))
                continue
            rows[section.value] = written.rows

        if len(failures) == len(_STEPS):
            reason = "; ".join(f"{failure.section}: {failure.reason}" for failure in failures)
            await workflow.execute_activity(
                finalize_snapshot,
                FinalizeSnapshotInput(team_id=input.team_id, snapshot_id=input.snapshot_id, error=reason),
                start_to_close_timeout=timedelta(minutes=1),
            )
            raise ApplicationError(f"Every scan step failed. {reason}", non_retryable=True)
        await workflow.execute_activity(
            finalize_snapshot,
            FinalizeSnapshotInput(team_id=input.team_id, snapshot_id=input.snapshot_id, failed_sections=failures),
            start_to_close_timeout=timedelta(minutes=1),
        )
        return rows


@workflow.defn(name=SCHEDULE_WORKFLOW_NAME)
class DataCatalogUsageScheduleWorkflow(PostHogWorkflow):
    """The weekly run: one scan per team with the usage flag on, one at a time."""

    inputs_cls = UsageScheduleInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: UsageScheduleInput | None = None) -> dict[str, int]:
        input = input or UsageScheduleInput()
        team_ids = await workflow.execute_activity(list_teams_due, start_to_close_timeout=timedelta(minutes=5))
        scanned = failed = 0
        for team_id in team_ids:
            try:
                snapshot_id = await workflow.execute_activity(
                    create_snapshot,
                    CreateSnapshotInput(team_id=team_id, lookback_days=input.lookback_days),
                    start_to_close_timeout=timedelta(minutes=1),
                )
                await workflow.execute_child_workflow(
                    DataCatalogUsageScanWorkflow.run,
                    UsageScanInput(team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=input.telemetry_team_id),
                    id=scan_workflow_id(snapshot_id),
                )
                scanned += 1
            except (ActivityError, ChildWorkflowError):
                # One team's failure is in its snapshot row; the other teams still get their scan.
                failed += 1
        return {"teams": len(team_ids), "scanned": scanned, "failed": failed}


def _reason(error: ActivityError) -> str:
    return str(error.cause or error)
