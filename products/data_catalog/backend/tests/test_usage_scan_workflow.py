import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import pytest
from unittest.mock import patch

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team

from products.data_catalog.backend.logic.usage_snapshots import SCAN_EXECUTION_TIMEOUT, SCAN_STOPPED_MESSAGE
from products.data_catalog.backend.temporal.usage_scan.activities import create_snapshot
from products.data_catalog.backend.temporal.usage_scan.types import (
    CreateSnapshotInput,
    FinalizeSnapshotInput,
    ScanStepInput,
    SectionWritten,
)
from products.data_catalog.backend.temporal.usage_scan.workflows import (
    _BOUNDED_RETRY_POLICY,
    _FINALIZE_TIMEOUT,
    _STEP_RETRY_POLICY,
    _STEPS,
    EVERY_STEP_FAILED_MESSAGE,
    STEP_FAILED_MESSAGE,
    STEP_SKIPPED_MESSAGE,
    DataCatalogUsageScanWorkflow,
    DataCatalogUsageScheduleWorkflow,
)

QUEUE = "test-data-catalog-usage-scan"
_ACTIVITIES = "products.data_catalog.backend.temporal.usage_scan.activities"
SNAPSHOTS = {1: uuid.UUID(int=1), 2: uuid.UUID(int=2), 4: uuid.UUID(int=4)}


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
async def test_a_failed_step_keeps_the_other_sections_and_only_a_full_failure_fails_the_scan(
    environment: WorkflowEnvironment,
) -> None:
    finalized: list[FinalizeSnapshotInput] = []
    created: list[CreateSnapshotInput] = []
    ran: list[tuple[int, str]] = []

    @activity.defn(name="data-catalog-usage-list-teams")
    async def list_teams() -> list[int]:
        return [1, 3, 2, 4]

    @activity.defn(name="data-catalog-usage-create-snapshot")
    async def create(input: CreateSnapshotInput) -> uuid.UUID:
        if input.team_id == 3:
            raise ApplicationError("A usage scan is already running for this team.", non_retryable=True)
        created.append(input)
        return SNAPSHOTS[input.team_id]

    def step(name: str) -> Callable[[ScanStepInput], Awaitable[SectionWritten]]:
        @activity.defn(name=name)
        async def run(input: ScanStepInput) -> SectionWritten:
            ran.append((input.team_id, name))
            if input.team_id == 2 or name == "data-catalog-usage-detect-adjusted-runs":
                raise ApplicationError("ClickHouse refused the query.", non_retryable=True)
            return SectionWritten(rows=1)

        return run

    @activity.defn(name="data-catalog-usage-finalize-snapshot")
    async def finalize(input: FinalizeSnapshotInput) -> None:
        finalized.append(input)
        if input.error == SCAN_STOPPED_MESSAGE:
            raise ApplicationError("The database refused the update.", non_retryable=True)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[DataCatalogUsageScheduleWorkflow, DataCatalogUsageScanWorkflow],
        activities=[
            list_teams,
            create,
            step("data-catalog-usage-collect-metric-runs"),
            step("data-catalog-usage-stitch-sessions"),
            step("data-catalog-usage-detect-adjusted-runs"),
            step("data-catalog-usage-collect-topics"),
            step("data-catalog-usage-collect-table-sources"),
            step("data-catalog-usage-find-uncovered"),
            finalize,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        result = await environment.client.execute_workflow(
            DataCatalogUsageScheduleWorkflow.run,
            None,
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
            execution_timeout=timedelta(days=1),
        )

    # Team 4 comes after the failed close of team 2's row, and still gets its scan.
    assert result == {"teams": 4, "scanned": 2, "failed": 2}
    assert all(team != 3 for team, _ in ran)
    partial, failed, closed_by_parent, later_team = finalized
    assert (partial.snapshot_id, partial.error) == (SNAPSHOTS[1], None)
    assert [(step.section, step.reason) for step in partial.failed_sections] == [
        ("adjusted_runs", STEP_FAILED_MESSAGE),
        ("topics", STEP_SKIPPED_MESSAGE),
    ]
    assert (1, "data-catalog-usage-collect-topics") not in ran
    # Every step after the stitch reads its conversations, so it runs before the adjusted runs.
    assert [name for team, name in ran if team == 1][:3] == [
        "data-catalog-usage-collect-metric-runs",
        "data-catalog-usage-stitch-sessions",
        "data-catalog-usage-detect-adjusted-runs",
    ]
    assert (failed.snapshot_id, failed.error) == (SNAPSHOTS[2], EVERY_STEP_FAILED_MESSAGE)
    assert (closed_by_parent.snapshot_id, closed_by_parent.error) == (SNAPSHOTS[2], SCAN_STOPPED_MESSAGE)
    assert "ClickHouse" not in repr(finalized)
    assert later_team.snapshot_id == SNAPSHOTS[4]
    assert len({input.snapshot_id for input in created}) == 3


@pytest.mark.asyncio
async def test_a_deleted_team_stops_snapshot_retries() -> None:
    with patch(f"{_ACTIVITIES}.create_usage_snapshot", side_effect=Team.DoesNotExist):
        with pytest.raises(ApplicationError) as raised:
            await ActivityEnvironment().run(
                create_snapshot, CreateSnapshotInput(team_id=1, lookback_days=28, snapshot_id=uuid.UUID(int=9))
            )

    assert raised.value.non_retryable


def test_every_step_with_every_retry_fits_inside_the_scan_timeout() -> None:
    attempts = _STEP_RETRY_POLICY.maximum_attempts
    steps = attempts * sum((timeout for _, _, timeout, _ in _STEPS), timedelta())
    backoff = (attempts - 1) * len(_STEPS) * _STEP_RETRY_POLICY.initial_interval
    finalize = _BOUNDED_RETRY_POLICY.maximum_attempts * _FINALIZE_TIMEOUT

    assert steps + backoff + finalize < SCAN_EXECUTION_TIMEOUT
