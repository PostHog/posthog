import uuid
import datetime as dt

import pytest
import unittest.mock

from django.utils import timezone

import pytest_asyncio
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

# Mirrors execute_dag.py: child id is materialize-view-{dag_id}-{node_id}-{ts}, and the
# parent (tier) id is execute-dag-{dag_id}:{interval_seconds}-{ts}.
PARENT_HOURLY = f"execute-dag-{DAG_ID}:3600-2026-07-24T13:00:00"
PARENT_QUARTER_HOURLY = f"execute-dag-{DAG_ID}:900-2026-07-24T13:00:00"


@pytest_asyncio.fixture
async def tier_jobs(ateam):
    """One RUNNING job per cadence tier of the same DAG, on disjoint nodes."""

    async def make(node_id: str, parent_workflow_id: str) -> DataModelingJob:
        return await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJobStatus.RUNNING,
            workflow_id=f"materialize-view-{DAG_ID}-{node_id}-2026-07-24T13:00:00",
            parent_workflow_id=parent_workflow_id,
        )

    yield {
        NODE_HOURLY: await make(NODE_HOURLY, PARENT_HOURLY),
        NODE_QUARTER_HOURLY: await make(NODE_QUARTER_HOURLY, PARENT_QUARTER_HOURLY),
        # Shares the hourly run's parent with NODE_HOURLY.
        NODE_MIGRATED: await make(NODE_MIGRATED, PARENT_HOURLY),
    }


async def _run_activity(team_id: int, node_ids: list[str] | None) -> tuple[list[str], unittest.mock.MagicMock]:
    """Run the activity against a stubbed Temporal client, recording which workflows it cancelled."""
    cancelled: list[str] = []
    handle = unittest.mock.MagicMock()
    handle.cancel = unittest.mock.AsyncMock()

    def get_workflow_handle(workflow_id: str) -> unittest.mock.MagicMock:
        cancelled.append(workflow_id)
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
    return cancelled, handle


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
    cancelled, handle = await _run_activity(ateam.pk, node_ids)

    for node_id, job in tier_jobs.items():
        await database_sync_to_async(job.refresh_from_db)()
        if node_id in expected_preempted:
            assert job.status == DataModelingJobStatus.FAILED
            assert job.error == PREEMPTED_ERROR
        else:
            assert job.status == DataModelingJobStatus.RUNNING
            assert job.error is None

    # Only the owned nodes' own materialize workflows are cancelled. Cancelling a parent
    # would cascade to its siblings via ParentClosePolicy.REQUEST_CANCEL, which is the
    # over-broad cancellation this scoping exists to prevent.
    assert sorted(cancelled) == sorted(tier_jobs[node_id].workflow_id for node_id in expected_preempted)
    assert not {PARENT_HOURLY, PARENT_QUARTER_HOURLY} & set(cancelled)
    assert handle.cancel.await_count == len(expected_preempted)


# Absolute ages, deliberately not derived from STALE_RUNNING_JOB_AGE — offsets from the constant
# would track any change to it and could never fail. A week is past any defensible threshold
# (activities cap at 20 minutes); a minute is unambiguously still live.
@pytest.mark.parametrize(
    "age,expect_reaped",
    [
        pytest.param(dt.timedelta(days=7), True, id="abandoned_row_is_reaped"),
        pytest.param(dt.timedelta(minutes=1), False, id="live_foreign_job_is_left_alone"),
    ],
)
async def test_rows_outside_our_nodes_are_reaped_only_once_their_workflow_is_gone(
    age: dt.timedelta,
    expect_reaped: bool,
    ateam,
    tier_jobs,
) -> None:
    # A node in no tier: nothing ever "owns" it, so if ownership gated cleanup its row would
    # stay Running forever and the UI would show it perpetually materializing.
    orphan_node = "44444444-4444-4444-4444-444444444444"
    orphan = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        status=DataModelingJobStatus.RUNNING,
        workflow_id=f"materialize-view-{DAG_ID}-{orphan_node}-2026-01-01T00:00:00",
        parent_workflow_id=PARENT_HOURLY,
    )
    # updated_at is auto_now, so age it with a queryset update rather than a save.
    await database_sync_to_async(DataModelingJob.objects.filter(id=orphan.id).update)(updated_at=timezone.now() - age)

    cancelled, _handle = await _run_activity(ateam.pk, [NODE_QUARTER_HOURLY])

    await database_sync_to_async(orphan.refresh_from_db)()
    if expect_reaped:
        assert orphan.status == DataModelingJobStatus.FAILED
        assert orphan.error == ABANDONED_ERROR
    else:
        assert orphan.status == DataModelingJobStatus.RUNNING
        assert orphan.error is None

    # Reaping only marks the row. There is no live workflow left to cancel, and cancelling on
    # another tier's behalf is precisely what this activity must not do.
    assert orphan.workflow_id not in cancelled
    assert cancelled == [tier_jobs[NODE_QUARTER_HOURLY].workflow_id]
