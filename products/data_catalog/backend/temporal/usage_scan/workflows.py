from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from ...facade.enums import UsageSection
    from ...logic.usage_scan import SCAN_WORKFLOW_NAME, scan_workflow_id
    from ...logic.usage_snapshots import SCAN_EXECUTION_TIMEOUT, SCAN_STOPPED_MESSAGE
    from .activities import (
        collect_metric_runs,
        collect_table_sources,
        collect_topics,
        create_snapshot,
        detect_adjusted_runs,
        finalize_snapshot,
        find_uncovered,
        list_teams_due,
        stitch_sessions,
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
# Sized to the judge call cap. With every retry, the steps still fit inside SCAN_EXECUTION_TIMEOUT.
_JUDGE_STEP = timedelta(hours=2)
# Sized to the page cap of human query shapes, which the step parses one by one, plus the drafts.
_UNCOVERED_STEP = timedelta(hours=2)
_FINALIZE_TIMEOUT = timedelta(minutes=1)
# An error that keeps coming back must not hold the later teams until the run times out.
_BOUNDED_RETRY_POLICY = common.RetryPolicy(maximum_attempts=5)
# The model steps heartbeat after each model call. The longest gap is the data load before the first
# call, plus one model call. The model client waits up to 10 minutes for each attempt of a call.
_MODEL_STEP_HEARTBEAT = timedelta(minutes=30)

# In run order: every later step reads the stitched conversations, and topics read the adjusted runs. A
# failed stitch leaves each session id as its own conversation. Steps that never heartbeat get no heartbeat
# timeout.
_STEPS = (
    (UsageSection.METRIC_RUNS, collect_metric_runs, _SHORT_STEP, None),
    (UsageSection.CONVERSATIONS, stitch_sessions, _LONG_STEP, _MODEL_STEP_HEARTBEAT),
    (UsageSection.ADJUSTED_RUNS, detect_adjusted_runs, _JUDGE_STEP, _MODEL_STEP_HEARTBEAT),
    (UsageSection.TOPICS, collect_topics, _LONG_STEP, _MODEL_STEP_HEARTBEAT),
    (UsageSection.TABLE_SOURCES, collect_table_sources, _LONG_STEP, None),
    (UsageSection.UNCOVERED, find_uncovered, _UNCOVERED_STEP, _MODEL_STEP_HEARTBEAT),
)
# The snapshot and the API show these fixed messages. The raw error goes to the worker log only.
STEP_FAILED_MESSAGE = "This step failed."
STEP_SKIPPED_MESSAGE = "This step did not run, because the adjusted runs step failed."
EVERY_STEP_FAILED_MESSAGE = "Every scan step failed."


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
        for section, step, timeout, heartbeat_timeout in _STEPS:
            # Topics count the adapted sessions from the adjusted runs. Without them, every count
            # would read as "no adapted sessions", so the step does not run.
            if section == UsageSection.TOPICS and any(
                failure.section == UsageSection.ADJUSTED_RUNS for failure in failures
            ):
                failures.append(FailedStep(section=section, reason=STEP_SKIPPED_MESSAGE))
                continue
            try:
                written = await workflow.execute_activity(
                    step,
                    step_input,
                    start_to_close_timeout=timeout,
                    heartbeat_timeout=heartbeat_timeout,
                    retry_policy=_STEP_RETRY_POLICY,
                )
            except ActivityError as error:
                workflow.logger.warning(
                    "data_catalog_usage_scan_step_failed",
                    extra={"section": section.value, "snapshot_id": str(input.snapshot_id), "error": _cause(error)},
                )
                failures.append(FailedStep(section=section, reason=STEP_FAILED_MESSAGE))
                continue
            rows[section.value] = written.rows

        if len(failures) == len(_STEPS):
            await workflow.execute_activity(
                finalize_snapshot,
                FinalizeSnapshotInput(
                    team_id=input.team_id,
                    snapshot_id=input.snapshot_id,
                    error=EVERY_STEP_FAILED_MESSAGE,
                    failed_sections=failures,
                ),
                start_to_close_timeout=_FINALIZE_TIMEOUT,
                retry_policy=_BOUNDED_RETRY_POLICY,
            )
            raise ApplicationError(EVERY_STEP_FAILED_MESSAGE, non_retryable=True)
        await workflow.execute_activity(
            finalize_snapshot,
            FinalizeSnapshotInput(team_id=input.team_id, snapshot_id=input.snapshot_id, failed_sections=failures),
            start_to_close_timeout=_FINALIZE_TIMEOUT,
            retry_policy=_BOUNDED_RETRY_POLICY,
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
        team_ids = await workflow.execute_activity(list_teams_due, start_to_close_timeout=timedelta(minutes=15))
        scanned = failed = 0
        for team_id in team_ids:
            try:
                snapshot_id = await workflow.execute_activity(
                    create_snapshot,
                    CreateSnapshotInput(
                        team_id=team_id, lookback_days=input.lookback_days, snapshot_id=workflow.uuid4()
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_BOUNDED_RETRY_POLICY,
                )
            except ActivityError:
                failed += 1
                continue
            try:
                await workflow.execute_child_workflow(
                    DataCatalogUsageScanWorkflow.run,
                    UsageScanInput(team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=input.telemetry_team_id),
                    id=scan_workflow_id(snapshot_id),
                    execution_timeout=SCAN_EXECUTION_TIMEOUT,
                    # If this run ends first, the scan in flight still finishes and closes its own row.
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                scanned += 1
            except ChildWorkflowError as error:
                # A timed-out scan never closes its row. The other teams still get their scan.
                failed += 1
                workflow.logger.warning(
                    "data_catalog_usage_scan_child_failed",
                    extra={"team_id": team_id, "snapshot_id": str(snapshot_id), "error": _cause(error)},
                )
                try:
                    await workflow.execute_activity(
                        finalize_snapshot,
                        FinalizeSnapshotInput(team_id=team_id, snapshot_id=snapshot_id, error=SCAN_STOPPED_MESSAGE),
                        start_to_close_timeout=_FINALIZE_TIMEOUT,
                        retry_policy=_BOUNDED_RETRY_POLICY,
                    )
                except ActivityError as close_error:
                    # The row stays computing, and reads report it as failed once the scan timeout passes.
                    workflow.logger.warning(
                        "data_catalog_usage_scan_close_failed",
                        extra={"team_id": team_id, "snapshot_id": str(snapshot_id), "error": _cause(close_error)},
                    )
        return {"teams": len(team_ids), "scanned": scanned, "failed": failed}


def _cause(error: ActivityError | ChildWorkflowError) -> str:
    return str(error.cause or error)
