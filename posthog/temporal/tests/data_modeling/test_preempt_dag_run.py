import uuid

import pytest
import unittest.mock

import pytest_asyncio
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import ActivityEnvironment

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities.preempt_dag_run import (
    ABANDONED_ERROR,
    PREEMPTED_ERROR,
    PreemptDAGRunInputs,
    preempt_dag_run_activity,
)

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

DAG_ID = "019e4d6a-1d8a-7569-97f5-a78ab8467820"
NODE_HOURLY = "11111111-1111-1111-1111-111111111111"
NODE_QUARTER_HOURLY = "22222222-2222-2222-2222-222222222222"
# Ran under the hourly tier, but a reconcile has since moved it to the 15-minute tier, so the
# 15-minute run now owns a node whose in-flight job belongs to the hourly run.
NODE_MIGRATED = "33333333-3333-3333-3333-333333333333"
# In no tier at all, so no run ever owns it.
NODE_ORPHAN = "44444444-4444-4444-4444-444444444444"

# Mirrors execute_dag.py: child id is materialize-view-{dag_id}-{node_id}-{ts}, and the
# parent (tier) id is execute-dag-{dag_id}:{interval_seconds}-{ts}.
PARENT_HOURLY = f"execute-dag-{DAG_ID}:3600-2026-07-24T13:00:00"
PARENT_QUARTER_HOURLY = f"execute-dag-{DAG_ID}:900-2026-07-24T13:00:00"


def _child_workflow_id(node_id: str) -> str:
    return f"materialize-view-{DAG_ID}-{node_id}-2026-07-24T13:00:00"


@pytest_asyncio.fixture
async def tier_jobs(ateam):
    """One RUNNING job per cadence tier of the same DAG, on disjoint nodes."""

    async def make(node_id: str, parent_workflow_id: str) -> DataModelingJob:
        return await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJobStatus.RUNNING,
            workflow_id=_child_workflow_id(node_id),
            parent_workflow_id=parent_workflow_id,
        )

    yield {
        NODE_HOURLY: await make(NODE_HOURLY, PARENT_HOURLY),
        NODE_QUARTER_HOURLY: await make(NODE_QUARTER_HOURLY, PARENT_QUARTER_HOURLY),
        # Shares the hourly run's parent with NODE_HOURLY.
        NODE_MIGRATED: await make(NODE_MIGRATED, PARENT_HOURLY),
    }


NOT_FOUND = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")
UNAVAILABLE = RPCError("temporal unavailable", RPCStatusCode.UNAVAILABLE, b"")


async def _run_activity(
    team_id: int,
    node_ids: list[str] | None,
    workflow_status: dict[str, WorkflowExecutionStatus | Exception] | None = None,
) -> list[str]:
    """Run the activity against a stubbed Temporal client, returning the workflows it cancelled.

    `workflow_status` maps a workflow id to what describe() does: a status to report, or an
    exception to raise. Anything unlisted is reported as still RUNNING.
    """
    cancelled: list[str] = []
    statuses: dict[str, WorkflowExecutionStatus | Exception] = workflow_status or {}

    def get_workflow_handle(workflow_id: str) -> unittest.mock.MagicMock:
        handle = unittest.mock.MagicMock()

        async def cancel() -> None:
            cancelled.append(workflow_id)

        async def describe() -> unittest.mock.MagicMock:
            outcome = statuses.get(workflow_id, WorkflowExecutionStatus.RUNNING)
            if isinstance(outcome, Exception):
                raise outcome
            description = unittest.mock.MagicMock()
            description.status = outcome
            return description

        handle.cancel = cancel
        handle.describe = describe
        return handle

    client = unittest.mock.MagicMock()
    client.get_workflow_handle = unittest.mock.MagicMock(side_effect=get_workflow_handle)

    with unittest.mock.patch(
        "posthog.temporal.data_modeling.activities.preempt_dag_run.async_connect",
        unittest.mock.AsyncMock(return_value=client),
    ):
        await ActivityEnvironment().run(
            preempt_dag_run_activity,
            PreemptDAGRunInputs(team_id=team_id, dag_id=DAG_ID, node_ids=node_ids),
        )
    return cancelled


@pytest.mark.parametrize(
    "node_ids,expected_preempted",
    [
        # The bug: the 15-minute tier must not touch the hourly tier's unrelated nodes.
        pytest.param([NODE_QUARTER_HOURLY], [NODE_QUARTER_HOURLY], id="scopes_to_own_tier"),
        # Claiming a node whose in-flight job belongs to another tier's run must not take that
        # run's siblings down with it — which cancelling the shared parent workflow would.
        pytest.param([NODE_MIGRATED], [NODE_MIGRATED], id="migrated_node_spares_its_old_runs_siblings"),
        # Legacy single whole-DAG schedule carries no node set and still preempts everything.
        pytest.param(None, [NODE_HOURLY, NODE_QUARTER_HOURLY, NODE_MIGRATED], id="no_node_ids_preempts_whole_dag"),
        # A tier whose nodes have no running jobs preempts nothing at all.
        pytest.param([str(uuid.uuid4())], [], id="unrelated_nodes_preempt_nothing"),
    ],
)
async def test_preempt_is_scoped_to_the_tiers_own_nodes(
    node_ids: list[str] | None,
    expected_preempted: list[str],
    ateam,
    tier_jobs,
) -> None:
    cancelled = await _run_activity(ateam.pk, node_ids)

    for node_id, job in tier_jobs.items():
        await database_sync_to_async(job.refresh_from_db)()
        if node_id in expected_preempted:
            assert job.status == DataModelingJobStatus.FAILED
            assert job.error == PREEMPTED_ERROR
        else:
            # Every other job's workflow reports RUNNING, so it is neither preempted nor reaped.
            assert job.status == DataModelingJobStatus.RUNNING
            assert job.error is None

    # Only the owned nodes' own materialize workflows are cancelled. Cancelling a parent
    # would cascade to its siblings via ParentClosePolicy.REQUEST_CANCEL, which is the
    # over-broad cancellation this scoping exists to prevent.
    assert sorted(cancelled) == sorted(_child_workflow_id(node_id) for node_id in expected_preempted)
    assert not {PARENT_HOURLY, PARENT_QUARTER_HOURLY} & set(cancelled)


@pytest.mark.parametrize(
    "status,expect_reaped",
    [
        pytest.param(WorkflowExecutionStatus.COMPLETED, True, id="closed_workflow_is_reaped"),
        pytest.param(WorkflowExecutionStatus.TERMINATED, True, id="terminated_workflow_is_reaped"),
        pytest.param(NOT_FOUND, True, id="missing_workflow_is_reaped"),
        # The one that age could not tell apart: still running, just slow. Nothing bounds a
        # materialization's wall clock, so this must be decided by status, not elapsed time.
        pytest.param(WorkflowExecutionStatus.RUNNING, False, id="slow_live_workflow_is_left_alone"),
        # A transient RPC failure proves nothing about the workflow. Treating it as "gone" would
        # mark a live job Failed without cancelling it — the exact corruption this fix prevents,
        # and unrecoverable because succeed_materialization won't overwrite a terminal status.
        pytest.param(UNAVAILABLE, False, id="transient_rpc_error_leaves_row_alone"),
    ],
)
async def test_rows_we_do_not_own_are_reaped_only_when_their_workflow_is_gone(
    status: WorkflowExecutionStatus | Exception,
    expect_reaped: bool,
    ateam,
    tier_jobs,
) -> None:
    # A node in no tier: nothing ever owns it, so if ownership gated cleanup its row would stay
    # Running forever and the UI would show it perpetually materializing.
    orphan = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        status=DataModelingJobStatus.RUNNING,
        workflow_id=_child_workflow_id(NODE_ORPHAN),
        parent_workflow_id=PARENT_HOURLY,
    )

    cancelled = await _run_activity(
        ateam.pk,
        [NODE_QUARTER_HOURLY],
        workflow_status={_child_workflow_id(NODE_ORPHAN): status},
    )

    await database_sync_to_async(orphan.refresh_from_db)()
    if expect_reaped:
        assert orphan.status == DataModelingJobStatus.FAILED
        assert orphan.error == ABANDONED_ERROR
    else:
        assert orphan.status == DataModelingJobStatus.RUNNING
        assert orphan.error is None

    # Reaping only marks the row. There is no live workflow left to cancel, and cancelling on
    # another tier's behalf is precisely what this activity must not do.
    assert cancelled == [_child_workflow_id(NODE_QUARTER_HOURLY)]


async def test_owned_workflows_are_cancelled_even_if_reaping_blows_up(ateam, tier_jobs) -> None:
    """Reaping makes one RPC per foreign row and can outrun the activity timeout. If that happened
    after the owned rows were marked Failed, a retry would no longer see them as Running and their
    workflows would never be cancelled — leaving the new run free to materialize the same node
    concurrently. Preemption must therefore complete before reaping is attempted at all."""
    await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        status=DataModelingJobStatus.RUNNING,
        workflow_id=_child_workflow_id(NODE_ORPHAN),
        parent_workflow_id=PARENT_HOURLY,
    )

    with unittest.mock.patch(
        "posthog.temporal.data_modeling.activities.preempt_dag_run._abandoned_jobs",
        unittest.mock.AsyncMock(side_effect=RuntimeError("reaping exploded")),
    ):
        cancelled = await _run_activity(ateam.pk, [NODE_QUARTER_HOURLY])

    owned = tier_jobs[NODE_QUARTER_HOURLY]
    await database_sync_to_async(owned.refresh_from_db)()
    assert owned.status == DataModelingJobStatus.FAILED
    assert owned.error == PREEMPTED_ERROR
    assert cancelled == [_child_workflow_id(NODE_QUARTER_HOURLY)]
