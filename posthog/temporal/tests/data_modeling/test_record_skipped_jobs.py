import dataclasses

import pytest

import pytest_asyncio
from temporalio.testing import ActivityEnvironment

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities.create_data_modeling_job import (
    RecordSkippedDataModelingJobsInputs,
    SkippedDataModelingNode,
    record_skipped_data_modeling_jobs_activity,
)

from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

WORKFLOW_ID = "execute-dag-019e4b57-31b8-7c8a-9d0e-5edaf66fa0ca:900-2026-08-07T11:17:00Z"


async def _make_node(team, dag, name):
    saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=team, name=name, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    node = await database_sync_to_async(Node.objects.create)(
        team=team, saved_query=saved_query, dag=dag, name=name, type=NodeType.MAT_VIEW
    )
    return node, saved_query


async def _run(team, dag, skipped_nodes):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=WORKFLOW_ID, workflow_run_id="run-1")
    await env.run(
        record_skipped_data_modeling_jobs_activity,
        RecordSkippedDataModelingJobsInputs(
            team_id=team.pk,
            dag_id=str(dag.id),
            engine=DataModelingJobEngine.CLICKHOUSE,
            skipped_nodes=skipped_nodes,
        ),
    )


@pytest_asyncio.fixture
async def adag_local(ateam):
    dag = await database_sync_to_async(DAG.objects.create)(team=ateam, name="skip-test-dag")
    yield dag
    await database_sync_to_async(dag.delete)()


class TestRecordSkippedDataModelingJobs:
    async def test_writes_a_skip_row_naming_every_blocking_upstream(self, ateam, adag_local):
        blocked, blocked_query = await _make_node(ateam, adag_local, "rollup_daily")
        parent_a, _ = await _make_node(ateam, adag_local, "orders_daily")
        parent_b, _ = await _make_node(ateam, adag_local, "customers_daily")

        await _run(
            ateam,
            adag_local,
            [
                SkippedDataModelingNode(
                    node_id=str(blocked.id),
                    failed_upstream_node_ids=[str(parent_a.id), str(parent_b.id)],
                    failed_upstream_total=2,
                )
            ],
        )

        job = await database_sync_to_async(
            lambda: DataModelingJob.objects.filter(saved_query_id=blocked_query.id).first()
        )()
        assert job is not None
        assert job.status == DataModelingJobStatus.SKIPPED
        assert job.rows_materialized == 0
        assert job.parent_workflow_id == WORKFLOW_ID
        assert job.error == "Skipped because upstream views orders_daily and customers_daily are failing."

    async def test_counts_the_upstreams_it_cannot_name(self, ateam, adag_local):
        blocked, blocked_query = await _make_node(ateam, adag_local, "rollup_daily")
        named = [(await _make_node(ateam, adag_local, f"source_{i}"))[0] for i in range(3)]

        await _run(
            ateam,
            adag_local,
            [
                SkippedDataModelingNode(
                    node_id=str(blocked.id),
                    failed_upstream_node_ids=[str(n.id) for n in named],
                    failed_upstream_total=17,
                )
            ],
        )

        job = await database_sync_to_async(
            lambda: DataModelingJob.objects.filter(saved_query_id=blocked_query.id).first()
        )()
        assert job is not None
        assert job.error == "Skipped because upstream views source_0, source_1, source_2 and 14 more are failing."

    async def test_does_not_write_a_second_row_for_the_same_fire(self, ateam, adag_local):
        blocked, blocked_query = await _make_node(ateam, adag_local, "rollup_daily")
        parent, _ = await _make_node(ateam, adag_local, "orders_daily")
        skipped = [
            SkippedDataModelingNode(
                node_id=str(blocked.id),
                failed_upstream_node_ids=[str(parent.id)],
                failed_upstream_total=1,
            )
        ]

        await _run(ateam, adag_local, skipped)
        await _run(ateam, adag_local, skipped)

        count = await database_sync_to_async(
            lambda: DataModelingJob.objects.filter(saved_query_id=blocked_query.id).count()
        )()
        assert count == 1
