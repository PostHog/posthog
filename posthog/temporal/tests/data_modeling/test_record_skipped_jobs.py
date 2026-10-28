import dataclasses

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import ActivityEnvironment

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities.check_upstream_reloads import (
    CheckUpstreamReloadsInputs,
    NodesWaitingOnUpstreamReloadsInputs,
    any_node_waiting_on_upstream_reloads_activity,
    check_upstream_reloads_activity,
)
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
    Edge,
    Node,
    NodeType,
)
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

CHECK_MODULE = "posthog.temporal.data_modeling.activities.check_upstream_reloads"
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


def _start_full_refresh_upstream_of(team, dag, node, *, previous_build: str = "stored") -> None:
    table = DataWarehouseTable.objects.create(name="stripe_charges", team=team)
    source = ExternalDataSource.objects.create(
        team=team, source_id="source_id", connection_id="connection_id", source_type="Stripe"
    )
    schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=table)
    table_node = Node.objects.create(
        team=team,
        dag=dag,
        name="stripe_charges",
        type=NodeType.TABLE,
        properties={"origin": "warehouse", "warehouse_table_id": str(table.id)},
    )
    Edge.objects.create(team=team, dag=dag, source=table_node, target=node)
    ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        schema_snapshot={"sync_type": "full_refresh"},
    )
    if previous_build in ("stored", "table_deleted"):
        DataModelingJob.objects.create(
            team=team,
            saved_query=node.saved_query,
            status=DataModelingJobStatus.COMPLETED,
            engine=DataModelingJobEngine.CLICKHOUSE,
        )
    if previous_build == "stored":
        stored = DataWarehouseTable.objects.create(name=node.saved_query.name, team=team)
        DataWarehouseSavedQuery.objects.filter(id=node.saved_query_id).update(table=stored)


async def _skip_if_reloading(team, dag, node):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=WORKFLOW_ID, workflow_run_id="run-1")
    return await env.run(
        check_upstream_reloads_activity,
        CheckUpstreamReloadsInputs(team_id=team.pk, dag_id=str(dag.id), node_id=str(node.id)),
    )


def _status_and_error(saved_query) -> list[tuple[str, str | None]]:
    return list(
        DataModelingJob.objects.filter(saved_query_id=saved_query.id)
        .exclude(status=DataModelingJobStatus.COMPLETED)
        .values_list("status", "error")
    )


class TestCheckUpstreamReloads:
    @pytest.mark.parametrize("previous_build", ["stored", "never_built", "table_deleted"])
    async def test_a_running_full_refresh_upstream_writes_one_skip_row_naming_the_table(
        self, ateam, adag_local, previous_build
    ):
        node, saved_query = await _make_node(ateam, adag_local, "revenue_daily")
        await database_sync_to_async(_start_full_refresh_upstream_of)(
            ateam, adag_local, node, previous_build=previous_build
        )

        result = await _skip_if_reloading(ateam, adag_local, node)
        # An activity retry runs the same check again.
        await _skip_if_reloading(ateam, adag_local, node)

        reason = (
            "Skipped because a sync is loading the upstream table stripe_charges again from the start. "
            "The view keeps its previous data and runs again when the sync finishes."
        )
        jobs = await database_sync_to_async(_status_and_error)(saved_query)
        if previous_build == "stored":
            assert result.reason == reason
            assert jobs == [(DataModelingJobStatus.SKIPPED, reason)]
        else:
            assert result.reason is None
            assert jobs == []

    @pytest.mark.parametrize(
        "node_name,other_run_status,other_workflow_status,waiting",
        [
            ("reloading", None, None, True),
            ("idle", None, None, False),
            ("idle", DataModelingJobStatus.RUNNING, WorkflowExecutionStatus.RUNNING, True),
            ("idle", DataModelingJobStatus.RUNNING, WorkflowExecutionStatus.TERMINATED, False),
            ("idle", DataModelingJobStatus.FAILED, None, False),
        ],
    )
    async def test_a_node_waits_on_a_reload_or_on_another_live_run_of_it(
        self, ateam, adag_local, node_name, other_run_status, other_workflow_status, waiting
    ):
        reloading, reloading_query = await _make_node(ateam, adag_local, "reloading")
        idle, idle_query = await _make_node(ateam, adag_local, "idle")
        await database_sync_to_async(_start_full_refresh_upstream_of)(ateam, adag_local, reloading)
        if other_run_status is not None:
            await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=idle_query,
                status=other_run_status,
                engine=DataModelingJobEngine.CLICKHOUSE,
                workflow_id="materialize-view-other-run",
            )
        temporal = MagicMock()
        temporal.get_workflow_handle.return_value.describe = AsyncMock(
            return_value=MagicMock(status=other_workflow_status)
        )
        node = reloading if node_name == "reloading" else idle

        with patch(f"{CHECK_MODULE}.async_connect", AsyncMock(return_value=temporal)):
            result = await ActivityEnvironment().run(
                any_node_waiting_on_upstream_reloads_activity,
                NodesWaitingOnUpstreamReloadsInputs(
                    team_id=ateam.pk, dag_id=str(adag_local.id), node_ids=[str(node.id)]
                ),
            )

        assert result is waiting
        assert await database_sync_to_async(_status_and_error)(reloading_query) == []
