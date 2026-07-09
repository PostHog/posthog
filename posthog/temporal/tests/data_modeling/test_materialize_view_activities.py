from collections.abc import Collection, Iterable
from typing import Any, cast

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
import deltalake
import pytest_asyncio

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities import (
    CreateDataModelingJobInputs,
    FailMaterializationInputs,
    MaterializeViewInputs,
    PrepareQueryableTableInputs,
    SucceedMaterializationInputs,
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
)
from posthog.temporal.data_modeling.activities.materialize_view import (
    InvalidNodeTypeException,
    _get_aws_storage_options,
)

from products.data_modeling.backend.facade.api import compute_enrichment_hash
from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)
from products.data_warehouse.backend.facade.api import CreateTableResult
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest_asyncio.fixture
async def asaved_query(ateam, auser):
    query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="test_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
        created_by=auser,
    )
    yield query
    await database_sync_to_async(query.delete)()


@pytest_asyncio.fixture
async def adag(ateam):
    dag = await database_sync_to_async(DAG.objects.create)(team=ateam, name="test-dag")
    yield dag
    await database_sync_to_async(dag.delete)()


@pytest_asyncio.fixture
async def anode(ateam, asaved_query, adag):
    node = await database_sync_to_async(Node.objects.create)(
        team=ateam,
        saved_query=asaved_query,
        dag=adag,
        name="test_model",
        type=NodeType.MAT_VIEW,
    )
    yield node
    await database_sync_to_async(node.delete)()


@pytest_asyncio.fixture
async def ajob(ateam, asaved_query):
    job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        saved_query=asaved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id="test-workflow",
    )
    yield job
    await database_sync_to_async(job.delete)()


async def _make_job(ateam, saved_query, status, *, engine=DataModelingJobEngine.CLICKHOUSE, error=None):
    return await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam, saved_query=saved_query, status=status, engine=engine, error=error
    )


class TestCreateDataModelingJobActivity:
    async def test_creates_job_with_running_status(self, activity_environment, ateam, auser, anode, asaved_query, adag):
        inputs = CreateDataModelingJobInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
        )
        with unittest.mock.patch("temporalio.activity.info") as mock_info:
            mock_info.return_value.workflow_id = "test-workflow-id"
            mock_info.return_value.workflow_run_id = "test-run-id"

            job_id = await activity_environment.run(create_data_modeling_job_activity, inputs)

        job = await database_sync_to_async(DataModelingJob.objects.get)(id=job_id)
        assert job.status == DataModelingJob.Status.RUNNING
        assert job.team_id == ateam.pk
        assert job.saved_query_id == asaved_query.id
        assert job.workflow_id == "test-workflow-id"
        assert job.workflow_run_id == "test-run-id"
        assert job.created_by_id == auser.id


class TestFailMaterializationActivity:
    async def test_marks_job_as_failed(self, activity_environment, ateam, anode, ajob, adag):
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            error="Test error message",
        )
        await activity_environment.run(fail_materialization_activity, inputs)
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == DataModelingJob.Status.FAILED
        assert ajob.rows_materialized == 0
        assert ajob.error == "Test error message"

    async def test_updates_node_system_properties(self, activity_environment, ateam, anode, ajob, adag):
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            error="Query failed: timeout",
        )
        await activity_environment.run(fail_materialization_activity, inputs)
        await database_sync_to_async(anode.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props["last_run_status"] == DataModelingJobStatus.FAILED
        assert system_props["last_run_job_id"] == str(ajob.id)
        assert system_props["last_run_error"] == "Query failed: timeout"
        assert "last_run_at" in system_props

    async def test_suspends_node_after_consecutive_failures(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended

        for _ in range(4):
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Some non-timeout error",
        )
        await activity_environment.run(fail_materialization_activity, inputs)

        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is True

    async def test_timeout_does_not_pause_schedule_with_fewer_than_5_previous_jobs(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        # Create only 3 previous failed timeout jobs - not enough to pause
        previous_jobs = []
        for i in range(3):
            job = await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=asaved_query,
                status=DataModelingJob.Status.FAILED,
                error="Timeout exceeded",
                workflow_id=f"prev-workflow-{i}",
            )
            previous_jobs.append(job)

        # Create current job
        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Timeout exceeded in query",
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.fail_materialization.pause_saved_query_schedule"
        ) as mock_pause:
            await activity_environment.run(fail_materialization_activity, inputs)
            mock_pause.assert_not_called()

        # Cleanup
        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_timeout_does_not_pause_schedule_when_previous_jobs_not_all_failures(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        # Create 5 previous jobs but one succeeded
        previous_jobs = []
        for i in range(5):
            status = DataModelingJob.Status.COMPLETED if i == 2 else DataModelingJob.Status.FAILED
            error = None if i == 2 else "Timeout exceeded"
            job = await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=asaved_query,
                status=status,
                error=error,
                workflow_id=f"prev-workflow-{i}",
            )
            previous_jobs.append(job)

        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Timeout exceeded in query",
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.fail_materialization.pause_saved_query_schedule"
        ) as mock_pause:
            await activity_environment.run(fail_materialization_activity, inputs)
            mock_pause.assert_not_called()

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_timeout_does_not_pause_schedule_when_previous_failures_not_all_timeouts(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        # Create 5 previous failed jobs but with different errors
        previous_jobs = []
        for i in range(5):
            error = "Memory limit exceeded" if i == 3 else "Timeout exceeded"
            job = await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=asaved_query,
                status=DataModelingJob.Status.FAILED,
                error=error,
                workflow_id=f"prev-workflow-{i}",
            )
            previous_jobs.append(job)

        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Timeout exceeded in query",
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.fail_materialization.pause_saved_query_schedule"
        ) as mock_pause:
            await activity_environment.run(fail_materialization_activity, inputs)
            mock_pause.assert_not_called()

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_timeout_pauses_schedule_after_5_consecutive_timeout_failures(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        # Create 5 previous timeout failed jobs
        previous_jobs = []
        for i in range(5):
            job = await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=asaved_query,
                status=DataModelingJob.Status.FAILED,
                error="Timeout exceeded",
                workflow_id=f"prev-workflow-{i}",
            )
            previous_jobs.append(job)

        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Timeout exceeded in query",
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.fail_materialization.pause_saved_query_schedule"
        ) as mock_pause:
            await activity_environment.run(fail_materialization_activity, inputs)
            mock_pause.assert_called_once_with(asaved_query)

        await database_sync_to_async(current_job.refresh_from_db)()
        assert current_job.error is not None
        assert "schedule has been paused" in current_job.error

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert asaved_query.sync_frequency_interval is None

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()


class TestShouldPauseScheduleForTimeout:
    async def test_returns_false_when_fewer_than_5_previous_jobs(self, ateam, asaved_query):
        from posthog.temporal.data_modeling.activities.fail_materialization import should_pause_schedule_for_timeout

        previous_jobs = []
        for i in range(3):
            job = await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=asaved_query,
                status=DataModelingJob.Status.FAILED,
                error="Timeout exceeded",
                workflow_id=f"prev-workflow-{i}",
            )
            previous_jobs.append(job)

        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        should_pause, count = await database_sync_to_async(should_pause_schedule_for_timeout)(
            asaved_query.id, current_job.id
        )
        assert should_pause is False
        assert count == 3

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_returns_true_when_5_consecutive_timeout_failures(self, ateam, asaved_query):
        from posthog.temporal.data_modeling.activities.fail_materialization import should_pause_schedule_for_timeout

        previous_jobs = []
        for i in range(5):
            job = await database_sync_to_async(DataModelingJob.objects.create)(
                team=ateam,
                saved_query=asaved_query,
                status=DataModelingJob.Status.FAILED,
                error="Timeout exceeded",
                workflow_id=f"prev-workflow-{i}",
            )
            previous_jobs.append(job)

        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        should_pause, count = await database_sync_to_async(should_pause_schedule_for_timeout)(
            asaved_query.id, current_job.id
        )
        assert should_pause is True
        assert count == 5

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_streak_ignores_jobs_from_other_engines(self, ateam, asaved_query):
        from posthog.temporal.data_modeling.activities.fail_materialization import should_pause_schedule_for_timeout

        for _ in range(5):
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="Timeout exceeded")
        # a more recent duckgres failure must not break the clickhouse timeout streak
        await _make_job(
            ateam, asaved_query, DataModelingJob.Status.FAILED, engine=DataModelingJobEngine.DUCKGRES, error="boom"
        )
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)

        should_pause, count = await database_sync_to_async(should_pause_schedule_for_timeout)(
            asaved_query.id, current_job.id
        )
        assert should_pause is True
        assert count == 5


class TestNodeSuspension:
    async def test_suspends_for_engine_after_consecutive_failures(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import (
            CONSECUTIVE_FAILURES_TO_SUSPEND,
            is_node_suspended,
            maybe_suspend_node_for_engine,
        )

        for _ in range(CONSECUTIVE_FAILURES_TO_SUSPEND):
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom",
            job_id=str(job.id),
        )

        assert suspended is True
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is True
        assert is_node_suspended(anode, DataModelingJobEngine.DUCKGRES) is False
        await database_sync_to_async(job.refresh_from_db)()
        assert "has been suspended" in job.error

    async def test_does_not_suspend_when_latest_run_succeeded(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, maybe_suspend_node_for_engine

        for _ in range(4):
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        await _make_job(ateam, asaved_query, DataModelingJob.Status.COMPLETED)

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom",
            job_id=str((await _make_job(ateam, asaved_query, DataModelingJob.Status.COMPLETED)).id),
        )

        assert suspended is False
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False

    async def test_does_not_restamp_when_already_suspended(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import maybe_suspend_node_for_engine

        for _ in range(5):
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        first_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        assert await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom",
            job_id=str(first_job.id),
        )

        next_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom again")
        suspended_again = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom again",
            job_id=str(next_job.id),
        )

        assert suspended_again is False
        await database_sync_to_async(next_job.refresh_from_db)()
        assert next_job.error == "boom again"

    async def test_engine_suspension_is_independent(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, maybe_suspend_node_for_engine

        for _ in range(5):
            await _make_job(
                ateam, asaved_query, DataModelingJob.Status.FAILED, engine=DataModelingJobEngine.DUCKGRES, error="boom"
            )
        job = await _make_job(
            ateam, asaved_query, DataModelingJob.Status.FAILED, engine=DataModelingJobEngine.DUCKGRES, error="boom"
        )

        kwargs = {
            "node_id": str(anode.id),
            "team_id": ateam.pk,
            "dag_id": str(adag.id),
            "saved_query_id": asaved_query.id,
            "reason": "boom",
            "job_id": str(job.id),
        }
        assert await maybe_suspend_node_for_engine(engine=DataModelingJobEngine.CLICKHOUSE, **kwargs) is False
        assert await maybe_suspend_node_for_engine(engine=DataModelingJobEngine.DUCKGRES, **kwargs) is True

        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.DUCKGRES) is True
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False
        # shadow-engine suspension must not stamp customer digest language onto the job
        await database_sync_to_async(job.refresh_from_db)()
        assert job.error == "boom"

    async def test_clear_suspension_only_affects_one_engine(self, ateam, anode, adag):
        from posthog.temporal.data_modeling.activities.utils import (
            clear_node_suspension_for_engine,
            is_node_suspended,
            mark_node_suspended,
        )

        mark_node_suspended(anode, engine=DataModelingJobEngine.CLICKHOUSE, reason="x", job_id="j1")
        mark_node_suspended(anode, engine=DataModelingJobEngine.DUCKGRES, reason="y", job_id="j2")
        await database_sync_to_async(anode.save)()

        cleared = await clear_node_suspension_for_engine(
            node_id=str(anode.id), team_id=ateam.pk, dag_id=str(adag.id), engine=DataModelingJobEngine.DUCKGRES
        )

        assert cleared is True
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.DUCKGRES) is False
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is True


class TestSucceedMaterializationActivity:
    async def test_marks_job_as_completed(self, activity_environment, ateam, anode, ajob, adag):
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=1000,
            duration_seconds=45.5,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == DataModelingJob.Status.COMPLETED
        assert ajob.error is None
        assert ajob.last_run_at is not None

    async def test_updates_node_system_properties(self, activity_environment, ateam, anode, ajob, adag):
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=500,
            duration_seconds=30.0,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)
        await database_sync_to_async(anode.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props["last_run_status"] == DataModelingJobStatus.COMPLETED
        assert system_props["last_run_job_id"] == str(ajob.id)
        assert system_props["last_run_rows"] == 500
        assert system_props["last_run_duration_seconds"] == 30.0
        assert system_props.get("last_run_error") is None
        assert "last_run_at" in system_props

    async def test_clears_previous_error(self, activity_environment, ateam, anode, ajob, adag):
        anode.properties = {"system": {"last_run_error": "Previous error"}}
        await database_sync_to_async(anode.save)()
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=100,
            duration_seconds=10.0,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)
        await database_sync_to_async(anode.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props.get("last_run_error") is None

    async def test_clears_clickhouse_suspension_on_success(self, activity_environment, ateam, anode, ajob, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, mark_node_suspended

        mark_node_suspended(anode, engine=DataModelingJobEngine.CLICKHOUSE, reason="x", job_id="old")
        mark_node_suspended(anode, engine=DataModelingJobEngine.DUCKGRES, reason="y", job_id="old")
        await database_sync_to_async(anode.save)()

        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=10,
            duration_seconds=1.0,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)

        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False
        assert is_node_suspended(anode, DataModelingJobEngine.DUCKGRES) is True

    async def test_flags_enrichment_needed_when_hash_missing(self, activity_environment, ateam, anode, ajob, adag):
        # A view with no stored enrichment hash (never enriched) must signal the workflow to enrich.
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=1,
            duration_seconds=1.0,
        )
        with unittest.mock.patch(
            "products.data_modeling.backend.logic.enrich_view_semantics.enrichment_enabled", return_value=True
        ):
            result = await activity_environment.run(succeed_materialization_activity, inputs)
        assert result.enrichment_needed is True
        assert result.saved_query_id == str(anode.saved_query_id)

    async def test_no_enrichment_when_flag_disabled(self, activity_environment, ateam, anode, ajob, adag):
        # A changed view must not signal enrichment when the feature flag is off, even with no stored hash.
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=1,
            duration_seconds=1.0,
        )
        with unittest.mock.patch(
            "products.data_modeling.backend.logic.enrich_view_semantics.enrichment_enabled", return_value=False
        ):
            result = await activity_environment.run(succeed_materialization_activity, inputs)
        assert result.enrichment_needed is False

    async def test_no_enrichment_when_hash_matches(self, activity_environment, ateam, anode, ajob, adag, asaved_query):
        # A steady-state re-materialization (stored hash still current) must not spawn an enrichment child.
        await database_sync_to_async(DataWarehouseSavedQuery.objects.filter(id=asaved_query.id).update)(
            semantic_enrichment_hash=compute_enrichment_hash(asaved_query)
        )
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            row_count=1,
            duration_seconds=1.0,
        )
        result = await activity_environment.run(succeed_materialization_activity, inputs)
        assert result.enrichment_needed is False


class TestPrepareQueryableTableActivity:
    async def test_creates_warehouse_table_from_saved_query(self, activity_environment, ateam, asaved_query, ajob):
        inputs = PrepareQueryableTableInputs(
            team_id=ateam.pk,
            job_id=str(ajob.id),
            saved_query_id=str(asaved_query.id),
            table_uri="s3://test-bucket/test_table",
            file_uris=["s3://test-bucket/test_file.parquet"],
            row_count=100,
        )
        warehouse_table = await database_sync_to_async(DataWarehouseTable.objects.create)(
            team=ateam,
            name="test_warehouse_table",
            format="Delta",
        )
        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.prepare_s3_files_for_querying"
            ) as mock_prepare,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.create_table_from_saved_query"
            ) as mock_create_table,
        ):
            mock_prepare.return_value = "test-bucket/queryable_folder"
            mock_create_table.return_value = CreateTableResult(
                table=warehouse_table, storage_delta_mib=None, total_storage_mib=None
            )
            await activity_environment.run(prepare_queryable_table_activity, inputs)
            mock_prepare.assert_called_once()
            mock_create_table.assert_called_once_with(
                str(ajob.id), str(asaved_query.id), ateam.pk, "test-bucket/queryable_folder"
            )
        await database_sync_to_async(warehouse_table.delete)()

    async def test_updates_saved_query_with_table_reference(self, activity_environment, ateam, asaved_query, ajob):
        inputs = PrepareQueryableTableInputs(
            team_id=ateam.pk,
            job_id=str(ajob.id),
            saved_query_id=str(asaved_query.id),
            table_uri="s3://test-bucket/test_table",
            file_uris=["s3://test-bucket/test_file.parquet"],
            row_count=250,
        )
        warehouse_table = await database_sync_to_async(DataWarehouseTable.objects.create)(
            team=ateam,
            name="test_warehouse_table",
            format="Delta",
        )
        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.prepare_s3_files_for_querying"
            ) as mock_prepare,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.create_table_from_saved_query"
            ) as mock_create_table,
        ):
            mock_prepare.return_value = "test-bucket/queryable_folder"
            mock_create_table.return_value = CreateTableResult(
                table=warehouse_table, storage_delta_mib=None, total_storage_mib=None
            )
            await activity_environment.run(prepare_queryable_table_activity, inputs)
            await database_sync_to_async(asaved_query.refresh_from_db)()
            assert asaved_query.table_id == warehouse_table.id
            await database_sync_to_async(warehouse_table.refresh_from_db)()
            assert warehouse_table.row_count == 250
        await database_sync_to_async(warehouse_table.delete)()


class TestMaterializeViewActivity:
    async def test_rejects_table_node_type(self, activity_environment, ateam, ajob, adag):
        table_node = await database_sync_to_async(Node.objects.create)(
            team=ateam,
            dag=adag,
            name="source_table",
            type=NodeType.TABLE,
        )
        inputs = MaterializeViewInputs(
            team_id=ateam.pk,
            dag_id=str(adag.id),
            node_id=str(table_node.id),
            job_id=str(ajob.id),
        )
        with pytest.raises(InvalidNodeTypeException, match="Cannot materialize a TABLE node"):
            await activity_environment.run(materialize_view_activity, inputs)
        await database_sync_to_async(table_node.delete)()

    async def test_materializes_view_to_delta_table(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        def mock_hogql_table(*args, **kwargs):
            del args, kwargs
            data = cast(
                Collection[pa.Array],
                [pa.array([1, 2, 3], type=pa.int64()), pa.array(["a", "b", "c"], type=pa.string())],
            )
            batch = pa.RecordBatch.from_arrays(data, names=["id", "name"])

            async def async_generator():
                yield batch, [("id", "Int64"), ("name", "String")]

            return async_generator()

        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", mock_hogql_table
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_query_row_count",
                return_value=3,
            ),
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)
            assert str(result.node_id) == str(anode.id)
            assert result.node_name == anode.name
            assert result.row_count == 3
            assert result.saved_query_id == str(asaved_query.id)
            assert f"team_{ateam.pk}_model_{asaved_query.id.hex}" in result.table_uri
            assert len(result.file_uris) > 0

    async def test_updates_job_progress_during_materialization(
        self, activity_environment, ateam, anode, ajob, bucket_name, adag
    ):
        def mock_hogql_table(*args, **kwargs):
            del args, kwargs  # unused
            batch1 = pa.RecordBatch.from_arrays([pa.array([1, 2], type=pa.int64())], names=["id"])
            batch2 = pa.RecordBatch.from_arrays([pa.array([3, 4, 5], type=pa.int64())], names=["id"])

            async def async_generator():
                yield batch1, [("id", "Int64")]
                yield batch2, [("id", "Int64")]

            return async_generator()

        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", mock_hogql_table
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_query_row_count",
                return_value=5,
            ),
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)
            await database_sync_to_async(ajob.refresh_from_db)()
            assert ajob.rows_expected == 5
            assert ajob.rows_materialized == 5
            assert result.row_count == 5

    async def test_preserves_column_casing_across_multiple_batches(
        self, activity_environment, ateam, anode, ajob, bucket_name, adag
    ):
        # regression: multiple batches with case-sensitive columns must materialize cleanly.
        #
        # delta-rs's DataFusion-backed append writer can lowercase identifiers and fail with
        # "Generic DeltaTable error: Schema error: No field named personid. ... Did you mean
        # 'personId'?" on tables whose column names contain uppercase characters. the activity
        # writes the first batch with mode="overwrite" (creating the table from the exact arrow
        # schema, pinning case) and appends later batches with schema_mode="merge" — the
        # data_imports write path. this asserts every batch's rows land and casing survives
        # across the overwrite + append commits.
        camel_case_names = ["Event", "DistinctId", "personId", "CamelCaseColumn"]

        def mock_hogql_table(*args, **kwargs):
            del args, kwargs
            batches = [
                pa.RecordBatch.from_arrays(
                    [pa.array([f"b{i}r0", f"b{i}r1"], type=pa.string()) for _ in camel_case_names],
                    names=camel_case_names,
                )
                for i in range(3)
            ]

            async def async_generator():
                for batch in batches:
                    yield batch, [(name, "String") for name in camel_case_names]

            return async_generator()

        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", mock_hogql_table
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_query_row_count",
                return_value=6,
            ),
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)

            assert result.row_count == 6
            delta_table = deltalake.DeltaTable(result.table_uri, storage_options=_get_aws_storage_options())
            materialized = delta_table.to_pyarrow_table()
            assert materialized.column_names == camel_case_names
            assert materialized.num_rows == 6

    async def test_preserves_column_casing_for_non_nullable_columns_across_batches(
        self, activity_environment, ateam, anode, ajob, bucket_name, adag
    ):
        # regression: ClickHouse emits NON-nullable columns for expressions, constants,
        # concat()/toString(), and non-Nullable source columns. When such a query spans more
        # than one batch, the first batch's overwrite pins a non-nullable delta schema and the
        # later append (schema_mode="merge") routes through delta-rs's DataFusion writer, which
        # lowercases identifiers and fails with:
        #   "Schema error: No field named userid. ... Did you mean 'userId'?"
        # for any column containing uppercase characters. This mirrors the customer query whose
        # camelCase columns (userId, portfolioId, pHuniqueId, aumDKK, ...) are all non-nullable.
        camel_case_names = ["date", "userId", "portfolioId", "pHuniqueId", "aumDKK", "aum_ETF"]
        non_nullable_schema = pa.schema([pa.field(name, pa.string(), nullable=False) for name in camel_case_names])

        def mock_hogql_table(*args, **kwargs):
            del args, kwargs
            batches = [
                pa.RecordBatch.from_arrays(
                    [pa.array([f"b{i}r0", f"b{i}r1"], type=pa.string()) for _ in camel_case_names],
                    schema=non_nullable_schema,
                )
                for i in range(3)
            ]

            async def async_generator():
                for batch in batches:
                    yield batch, [(name, "String") for name in camel_case_names]

            return async_generator()

        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", mock_hogql_table
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_query_row_count",
                return_value=6,
            ),
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)

            assert result.row_count == 6
            delta_table = deltalake.DeltaTable(result.table_uri, storage_options=_get_aws_storage_options())
            materialized = delta_table.to_pyarrow_table()
            assert materialized.column_names == camel_case_names
            assert materialized.num_rows == 6

    async def test_zero_row_materialization_writes_empty_parquet(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # regression: a zero-row query must still produce a queryable empty table.
        #
        # delta-rs writes no parquet data file for an empty batch, so the activity
        # synthesizes one carrying the schema and returns it as file_uris. without
        # this, prepare_queryable_table_activity would later list a never-created
        # S3 folder and raise FileNotFoundError.
        fields: Iterable[pa.Field[Any]] = [pa.field("id", pa.int64()), pa.field("name", pa.string())]
        empty_schema = pa.schema(fields)

        def mock_hogql_table(*args, **kwargs):
            del args, kwargs
            empty_batch = pa.RecordBatch.from_arrays(
                [pa.array([], type=f.type) for f in empty_schema], schema=empty_schema
            )

            async def async_generator():
                yield empty_batch, [("id", "Int64"), ("name", "String")]

            return async_generator()

        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", mock_hogql_table
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_query_row_count",
                return_value=0,
            ),
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)
            assert result.row_count == 0
            assert len(result.file_uris) == 1
            assert result.file_uris[0].endswith(".parquet")
            # delta log carries the schema so deltaLake() reads in get_columns succeed
            delta_table = deltalake.DeltaTable(result.table_uri, storage_options=_get_aws_storage_options())
            pyarrow_table = delta_table.to_pyarrow_table()
            assert pyarrow_table.num_rows == 0
            assert set(pyarrow_table.column_names) == {"id", "name"}

    async def test_write_failure_surfaces(self, activity_environment, ateam, anode, ajob, bucket_name, adag):
        # regression: a failure in a per-batch write_deltalake call must surface from the
        # activity so Temporal retries, rather than being swallowed.
        names = ["a", "b"]

        def mock_hogql_table(*args, **kwargs):
            del args, kwargs

            async def async_generator():
                for i in range(8):
                    batch = pa.RecordBatch.from_arrays(
                        [pa.array([f"b{i}r0", f"b{i}r1"], type=pa.string()) for _ in names],
                        names=names,
                    )
                    yield batch, [(name, "String") for name in names]

            return async_generator()

        def raising_write(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("boom")

        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", mock_hogql_table
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_query_row_count",
                return_value=16,
            ),
            unittest.mock.patch("deltalake.write_deltalake", side_effect=raising_write),
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            with pytest.raises(RuntimeError, match="boom"):
                await activity_environment.run(materialize_view_activity, inputs)
