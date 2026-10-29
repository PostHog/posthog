import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.data_catalog.backend.temporal.usage_scan.types import (
    CreateSnapshotInput,
    FinalizeSnapshotInput,
    ScanStepInput,
    SectionWritten,
)
from products.data_catalog.backend.temporal.usage_scan.workflows import (
    DataCatalogUsageScanWorkflow,
    DataCatalogUsageScheduleWorkflow,
)

QUEUE = "test-data-catalog-usage-scan"
SNAPSHOTS = {1: uuid.UUID(int=1), 2: uuid.UUID(int=2)}


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
async def test_a_failed_step_keeps_the_other_sections_and_only_a_full_failure_fails_the_scan(
    environment: WorkflowEnvironment,
) -> None:
    finalized: list[FinalizeSnapshotInput] = []

    @activity.defn(name="data-catalog-usage-list-teams")
    async def list_teams() -> list[int]:
        return [1, 2]

    @activity.defn(name="data-catalog-usage-create-snapshot")
    async def create(input: CreateSnapshotInput) -> uuid.UUID:
        return SNAPSHOTS[input.team_id]

    def step(name: str) -> Callable[[ScanStepInput], Awaitable[SectionWritten]]:
        @activity.defn(name=name)
        async def run(input: ScanStepInput) -> SectionWritten:
            if input.team_id == 2 or name == "data-catalog-usage-detect-adjusted-runs":
                raise ApplicationError("ClickHouse refused the query.", non_retryable=True)
            return SectionWritten(rows=1)

        return run

    @activity.defn(name="data-catalog-usage-finalize-snapshot")
    async def finalize(input: FinalizeSnapshotInput) -> None:
        finalized.append(input)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[DataCatalogUsageScheduleWorkflow, DataCatalogUsageScanWorkflow],
        activities=[
            list_teams,
            create,
            step("data-catalog-usage-collect-metric-runs"),
            step("data-catalog-usage-detect-adjusted-runs"),
            step("data-catalog-usage-collect-topics"),
            step("data-catalog-usage-find-uncovered"),
            finalize,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        result = await environment.client.execute_workflow(
            DataCatalogUsageScheduleWorkflow.run, None, id=f"test-{uuid.uuid4()}", task_queue=QUEUE
        )

    assert result == {"teams": 2, "scanned": 1, "failed": 1}
    partial, failed = finalized
    assert (partial.snapshot_id, partial.error) == (SNAPSHOTS[1], None)
    assert [(step.section, step.reason) for step in partial.failed_sections] == [
        ("adjusted_runs", "ClickHouse refused the query.")
    ]
    assert failed.snapshot_id == SNAPSHOTS[2]
    assert "uncovered: ClickHouse refused the query." in (failed.error or "")
