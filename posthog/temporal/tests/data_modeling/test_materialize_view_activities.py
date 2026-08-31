import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable, Collection, Iterable
from dataclasses import replace
from io import BytesIO
from typing import Any, cast
from uuid import uuid4

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
import deltalake
import pyarrow.parquet as pq

from posthog.hogql.resolver import ResolverFactory

from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import ClickHouseError
from posthog.temporal.data_modeling.activities import (
    CreateDataModelingJobInputs,
    FailMaterializationInputs,
    MaterializeViewInputs,
    PrepareQueryableTableInputs,
    QualityBlockMaterializationInputs,
    SucceedMaterializationInputs,
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
    quality_block_materialization_activity,
    succeed_materialization_activity,
)
from posthog.temporal.data_modeling.activities.materialize_view import (
    LOGGER,
    InvalidNodeTypeException,
    get_aws_storage_options,
    get_s3_client,
    hogql_table,
)
from posthog.temporal.data_modeling.activities.notify_materialization_failure import _SavedQueryViewers

from products.customer_analytics.backend.facade.temporal import stage_warehouse_account_property_files_activity
from products.customer_analytics.backend.facade.temporal_contracts import StageAccountPropertySyncInput
from products.data_modeling.backend.facade.api import compute_enrichment_hash
from products.data_modeling.backend.facade.modeling import bounded_resolver_factory_for_view
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)
from products.data_warehouse.backend.facade.api import CreateTableResult
from products.notifications.backend.facade.api import NotificationType, TargetType
from products.warehouse_sources.backend.facade.hooks import (
    AccountPropertySourceProjection,
    PersonPropertySourceProjection,
    saved_query_binding,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.temporal import (
    account_property_job_staged_prefix,
    person_property_job_staged_prefix,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def _make_job(
    ateam, saved_query, status, *, engine=DataModelingJobEngine.CLICKHOUSE, error=None, parent_workflow_id=None
):
    return await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        saved_query=saved_query,
        status=status,
        engine=engine,
        error=error,
        parent_workflow_id=parent_workflow_id,
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
    @pytest.mark.parametrize(
        "cancelled,expected_status",
        [(False, DataModelingJob.Status.FAILED), (True, DataModelingJob.Status.CANCELLED)],
    )
    async def test_marks_job_as_terminal(
        self, activity_environment, ateam, anode, ajob, adag, cancelled, expected_status
    ):
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            error="Test error message",
            cancelled=cancelled,
        )
        await activity_environment.run(fail_materialization_activity, inputs)
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == expected_status
        assert ajob.rows_materialized == 0
        assert ajob.error == "Test error message"
        # The UI derives run duration and the log-search window from last_run_at, so a
        # terminal transition must stamp it (the model default is the job's start time).
        assert ajob.last_run_at > ajob.created_at

    async def test_does_not_overwrite_already_terminal_job(self, activity_environment, ateam, anode, ajob, adag):
        ajob.status = DataModelingJob.Status.COMPLETED
        await database_sync_to_async(ajob.save)()
        await database_sync_to_async(ajob.refresh_from_db)()
        completed_last_run_at = ajob.last_run_at

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            error="Late failure",
        )
        await activity_environment.run(fail_materialization_activity, inputs)
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == DataModelingJob.Status.COMPLETED
        assert ajob.error is None
        assert ajob.last_run_at == completed_last_run_at

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

    @pytest.mark.parametrize(
        "previous_status,expect_notification",
        [
            (None, True),
            (DataModelingJob.Status.COMPLETED, True),
            (DataModelingJob.Status.FAILED, False),
        ],
    )
    async def test_notifies_only_on_first_failure_of_streak(
        self, activity_environment, ateam, anode, asaved_query, adag, previous_status, expect_notification
    ):
        if previous_status is not None:
            error = "boom" if previous_status == DataModelingJob.Status.FAILED else None
            await _make_job(ateam, asaved_query, previous_status, error=error)
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Some non-timeout error",
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
        ) as mock_create:
            await activity_environment.run(fail_materialization_activity, inputs)

        if expect_notification:
            mock_create.assert_called_once()
            data = mock_create.call_args.args[0]
            assert data.notification_type == NotificationType.MATERIALIZATION_FAILURE
            assert data.target_id == str(ateam.pk)
            assert data.resource_id == str(asaved_query.id)
        else:
            mock_create.assert_not_called()

    @pytest.mark.parametrize("intervening_status", [DataModelingJob.Status.CANCELLED, DataModelingJob.Status.RUNNING])
    async def test_an_inconclusive_run_does_not_restart_the_streak(
        self, activity_environment, ateam, anode, asaved_query, adag, intervening_status
    ):
        await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        await _make_job(ateam, asaved_query, intervening_status)
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Some non-timeout error",
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
        ) as mock_create:
            await activity_environment.run(fail_materialization_activity, inputs)

        mock_create.assert_not_called()

    async def test_notifies_when_recovery_raises(self, activity_environment, ateam, anode, asaved_query, adag):
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Some non-timeout error",
        )
        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.fail_materialization.maybe_suspend_node_for_engine",
                side_effect=Exception("suspension blew up"),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            await activity_environment.run(fail_materialization_activity, inputs)

        mock_create.assert_called_once()

    async def test_does_not_notify_when_cancelled(self, activity_environment, ateam, anode, asaved_query, adag):
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)

        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="Workflow was cancelled",
            cancelled=True,
        )
        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
        ) as mock_create:
            await activity_environment.run(fail_materialization_activity, inputs)

        mock_create.assert_not_called()

    async def test_notification_resolver_drops_members_denied_on_the_view(
        self, activity_environment, ateam, anode, asaved_query, adag, aorganization
    ):
        # These tests share a database, so the emails have to be unique per run.
        allowed = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"allowed-{uuid4()}@posthog.com", None
        )
        denied = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"denied-{uuid4()}@posthog.com", None
        )

        class FakeAccess:
            def __init__(self, user, team):
                self._user = user

            is_organization_admin = False

            def check_access_level_for_object(self, obj, required_level):
                return self._user.id == allowed.id

        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl", FakeAccess
        ):
            resolved = await database_sync_to_async(_SavedQueryViewers(asaved_query).resolve)(
                TargetType.TEAM, str(ateam.pk), ateam.pk
            )

        assert allowed.id in resolved
        assert denied.id not in resolved

    async def test_a_child_of_a_dag_run_leaves_the_in_app_notification_to_its_parent(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        current_job = await _make_job(
            ateam, asaved_query, DataModelingJob.Status.RUNNING, parent_workflow_id="execute-dag-workflow"
        )
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="boom",
        )

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.send_matview_failure_immediate_email"
            ) as mock_email,
        ):
            await activity_environment.run(fail_materialization_activity, inputs)

        mock_create.assert_not_called()
        mock_email.delay.assert_called_once()

    async def test_notification_carries_the_per_view_resolver(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(current_job.id),
            error="boom",
        )

        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
        ) as mock_create:
            await activity_environment.run(fail_materialization_activity, inputs)

        resolver = mock_create.call_args.args[0].resolver
        assert isinstance(resolver, _SavedQueryViewers)

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


class TestQualityBlockMaterializationActivity:
    async def test_a_blocked_publish_fails_the_node_and_job_but_starts_no_recovery(
        self, activity_environment, ateam, anode, asaved_query, adag
    ):
        job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)
        inputs = QualityBlockMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(job.id),
            blocking_failures=2,
        )

        await activity_environment.run(quality_block_materialization_activity, inputs)

        await database_sync_to_async(anode.refresh_from_db)()
        await database_sync_to_async(job.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props["last_run_status"] == DataModelingJobStatus.FAILED
        assert "2 data quality checks failed" in system_props["last_run_error"]
        assert job.status == DataModelingJob.Status.FAILED
        assert "2 data quality checks failed" in job.error
        assert "suspended" not in system_props

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
            asaved_query.id, current_job
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
            asaved_query.id, current_job
        )
        assert should_pause is True
        assert count == 5

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_streak_survives_a_run_skipped_for_an_upstream_failure(self, ateam, asaved_query):
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

        skipped = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.SKIPPED,
            error="Skipped because upstream view orders_daily is failing.",
            workflow_id="skipped-workflow",
        )
        previous_jobs.append(skipped)

        current_job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            saved_query=asaved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="current-workflow",
        )

        should_pause, count = await database_sync_to_async(should_pause_schedule_for_timeout)(
            asaved_query.id, current_job
        )
        assert should_pause is True
        assert count == 5

        await database_sync_to_async(current_job.delete)()
        for job in previous_jobs:
            await database_sync_to_async(job.delete)()

    async def test_streak_ignores_jobs_from_other_engines(self, ateam, asaved_query):
        from posthog.temporal.data_modeling.activities.fail_materialization import should_pause_schedule_for_timeout

        jobs = [
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="Timeout exceeded")
            for _ in range(5)
        ]
        # a more recent duckgres failure must not break the clickhouse timeout streak
        jobs.append(
            await _make_job(
                ateam, asaved_query, DataModelingJob.Status.FAILED, engine=DataModelingJobEngine.DUCKGRES, error="boom"
            )
        )
        current_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.RUNNING)
        jobs.append(current_job)

        should_pause, count = await database_sync_to_async(should_pause_schedule_for_timeout)(
            asaved_query.id, current_job
        )
        assert should_pause is True
        assert count == 5

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()


class TestNodeSuspension:
    @pytest.mark.parametrize("enforced", [True, False])
    async def test_suspends_for_engine_after_consecutive_failures(self, ateam, anode, asaved_query, adag, enforced):
        from posthog.temporal.data_modeling.activities.utils import (
            CONSECUTIVE_FAILURES_TO_SUSPEND,
            is_node_suspended,
            maybe_suspend_node_for_engine,
        )

        jobs = [
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
            for _ in range(CONSECUTIVE_FAILURES_TO_SUSPEND)
        ]
        job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        jobs.append(job)

        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.utils.is_suspension_enforced", return_value=enforced
        ):
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
        assert ("has been suspended" in job.error) is enforced

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for j in jobs:
            await database_sync_to_async(j.delete)()

    @pytest.mark.parametrize(
        "aborted_error",
        [
            "Code: 202. DB::Exception: Too many simultaneous queries",
            "Cannot connect to host ch-offline.example.com:8443",
            "Abandoned: the materialization workflow is no longer running",
            "QueueEmpty: Application error",
            "Preempted: a new DAG run started before this job completed",
            "Not published: 2 data quality checks failed. The previous version keeps serving until the checks pass.",
        ],
    )
    async def test_externally_aborted_failures_do_not_suspend(self, ateam, anode, asaved_query, adag, aborted_error):
        from posthog.temporal.data_modeling.activities.utils import (
            CONSECUTIVE_FAILURES_TO_SUSPEND,
            is_node_suspended,
            maybe_suspend_node_for_engine,
        )

        jobs = [
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error=aborted_error)
            for _ in range(CONSECUTIVE_FAILURES_TO_SUSPEND)
        ]

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason=aborted_error,
            job_id=str(jobs[-1].id),
        )

        assert suspended is False
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()

    @pytest.mark.parametrize("identifier", ["Preempted", "QueueEmpty"])
    async def test_suspends_when_a_customer_identifier_spells_an_abort_marker(
        self, ateam, anode, asaved_query, adag, identifier
    ):
        from posthog.temporal.data_modeling.activities.utils import (
            CONSECUTIVE_FAILURES_TO_SUSPEND,
            is_node_suspended,
            maybe_suspend_node_for_engine,
        )

        error = f"Code: 47. DB::Exception: Missing columns: '{identifier}' while processing query"
        jobs = [
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error=error)
            for _ in range(CONSECUTIVE_FAILURES_TO_SUSPEND)
        ]

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason=error,
            job_id=str(jobs[-1].id),
        )

        assert suspended is True
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is True

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()

    @pytest.mark.parametrize(
        "memory_error",
        [
            "ClickHouseMemoryLimitExceededError: Code: 241. DB::Exception: Memory limit (for query) exceeded",
            "ClickHouseMemoryLimitExceededError: Code: 241. DB::Exception: (total) memory limit exceeded",
            "ClickHouseMemoryLimitExceededError: Code: 241. DB::Exception: Query memory limit exceeded",
        ],
    )
    async def test_suspends_when_the_query_exhausts_memory(self, ateam, anode, asaved_query, adag, memory_error):
        from posthog.temporal.data_modeling.activities.utils import (
            CONSECUTIVE_FAILURES_TO_SUSPEND,
            is_node_suspended,
            maybe_suspend_node_for_engine,
        )

        jobs = [
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error=memory_error)
            for _ in range(CONSECUTIVE_FAILURES_TO_SUSPEND)
        ]

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason=memory_error,
            job_id=str(jobs[-1].id),
        )

        assert suspended is True
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is True

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()

    async def test_infrastructure_failure_breaks_a_customer_streak(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, maybe_suspend_node_for_engine

        jobs = [await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom") for _ in range(4)]
        jobs.append(
            await _make_job(
                ateam, asaved_query, DataModelingJob.Status.FAILED, error="Code: 202. Too many simultaneous queries"
            )
        )
        job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        jobs.append(job)

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom",
            job_id=str(job.id),
        )

        assert suspended is False
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for j in jobs:
            await database_sync_to_async(j.delete)()

    async def test_does_not_suspend_when_latest_run_succeeded(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, maybe_suspend_node_for_engine

        jobs = [await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom") for _ in range(4)]
        jobs.append(await _make_job(ateam, asaved_query, DataModelingJob.Status.COMPLETED))
        last_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.COMPLETED)
        jobs.append(last_job)

        suspended = await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom",
            job_id=str(last_job.id),
        )

        assert suspended is False
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()

    async def test_does_not_restamp_when_already_suspended(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import maybe_suspend_node_for_engine

        jobs = [await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom") for _ in range(5)]
        first_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        jobs.append(first_job)
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
        jobs.append(next_job)
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

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()

    async def test_skipped_runs_do_not_break_the_failure_streak(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import (
            CONSECUTIVE_FAILURES_TO_SUSPEND,
            is_node_suspended,
            maybe_suspend_node_for_engine,
        )

        jobs = [
            await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
            for _ in range(CONSECUTIVE_FAILURES_TO_SUSPEND - 1)
        ]
        # an upstream failure parks this node for one run; it never got to succeed
        jobs.append(await _make_job(ateam, asaved_query, DataModelingJob.Status.SKIPPED, error="upstream failed"))
        job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        jobs.append(job)

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

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for j in jobs:
            await database_sync_to_async(j.delete)()

    async def test_does_not_resuspend_on_failures_from_before_a_resume(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, maybe_suspend_node_for_engine

        from products.data_modeling.backend.facade.api import resume_nodes

        jobs = [await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom") for _ in range(5)]
        first_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom")
        jobs.append(first_job)
        assert await maybe_suspend_node_for_engine(
            node_id=str(anode.id),
            team_id=ateam.pk,
            dag_id=str(adag.id),
            saved_query_id=asaved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            reason="boom",
            job_id=str(first_job.id),
        )

        await database_sync_to_async(anode.refresh_from_db)()
        await database_sync_to_async(resume_nodes)([anode], by="query_edit")

        next_job = await _make_job(ateam, asaved_query, DataModelingJob.Status.FAILED, error="boom again")
        jobs.append(next_job)
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
        await database_sync_to_async(anode.refresh_from_db)()
        assert is_node_suspended(anode, DataModelingJobEngine.CLICKHOUSE) is False

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for job in jobs:
            await database_sync_to_async(job.delete)()

    async def test_engine_suspension_is_independent(self, ateam, anode, asaved_query, adag):
        from posthog.temporal.data_modeling.activities.utils import is_node_suspended, maybe_suspend_node_for_engine

        jobs = [
            await _make_job(
                ateam, asaved_query, DataModelingJob.Status.FAILED, engine=DataModelingJobEngine.DUCKGRES, error="boom"
            )
            for _ in range(5)
        ]
        job = await _make_job(
            ateam, asaved_query, DataModelingJob.Status.FAILED, engine=DataModelingJobEngine.DUCKGRES, error="boom"
        )
        jobs.append(job)

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

        # DataModelingJob.team is SET_NULL, so it survives the ateam fixture's team teardown.
        for j in jobs:
            await database_sync_to_async(j.delete)()

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
        result = await activity_environment.run(succeed_materialization_activity, inputs)
        assert result.enrichment_needed is True
        assert result.saved_query_id == str(anode.saved_query_id)

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

    async def test_passes_refresh_file_uris_that_re_reads_the_delta_table(
        self, activity_environment, ateam, asaved_query, ajob
    ):
        # Regression: this call site used to omit refresh_file_uris, so a source file a concurrent
        # compact/vacuum pass deleted mid-copy raised FileNotFoundError straight through instead of
        # retrying with a fresh listing (see prepare_s3_files_for_querying's vanished-file handling).
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
        refreshed_file_uris = ["s3://test-bucket/test_table/compacted.parquet"]
        mock_delta_table = unittest.mock.MagicMock()
        mock_delta_table.file_uris.return_value = refreshed_file_uris
        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.prepare_s3_files_for_querying"
            ) as mock_prepare,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.create_table_from_saved_query"
            ) as mock_create_table,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.get_aws_storage_options",
                return_value={},
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.prepare_queryable_table.deltalake.DeltaTable",
                return_value=mock_delta_table,
            ) as mock_delta_table_cls,
        ):
            mock_prepare.return_value = "test-bucket/queryable_folder"
            mock_create_table.return_value = CreateTableResult(
                table=warehouse_table, storage_delta_mib=None, total_storage_mib=None
            )
            await activity_environment.run(prepare_queryable_table_activity, inputs)

            refresh_file_uris = mock_prepare.call_args.kwargs["refresh_file_uris"]
            assert await refresh_file_uris() == refreshed_file_uris
            mock_delta_table_cls.assert_called_once_with(inputs.table_uri, storage_options={})
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

    async def test_retypes_view_node_to_matview_once_a_table_is_linked(
        self, activity_environment, ateam, asaved_query, anode, ajob
    ):
        # revert_materialization leaves the node typed VIEW; every scheduled DAG run then treats
        # it as ephemeral and skips materialization without recording a job.
        anode.type = NodeType.VIEW
        await database_sync_to_async(anode.save)()

        inputs = PrepareQueryableTableInputs(
            team_id=ateam.pk,
            job_id=str(ajob.id),
            saved_query_id=str(asaved_query.id),
            table_uri="s3://test-bucket/test_table",
            file_uris=["s3://test-bucket/test_file.parquet"],
            row_count=10,
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

        await database_sync_to_async(anode.refresh_from_db)()
        assert anode.type == NodeType.MAT_VIEW
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
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)
            await database_sync_to_async(ajob.refresh_from_db)()
            assert ajob.rows_expected is None
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
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)

            assert result.row_count == 6
            delta_table = deltalake.DeltaTable(result.table_uri, storage_options=get_aws_storage_options())
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
        ):
            inputs = MaterializeViewInputs(
                team_id=ateam.pk,
                dag_id=str(adag.id),
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)

            assert result.row_count == 6
            delta_table = deltalake.DeltaTable(result.table_uri, storage_options=get_aws_storage_options())
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
            delta_table = deltalake.DeltaTable(result.table_uri, storage_options=get_aws_storage_options())
            pyarrow_table = delta_table.to_pyarrow_table()
            assert pyarrow_table.num_rows == 0
            assert set(pyarrow_table.column_names) == {"id", "name"}
            # ClickHouse rejects a parquet containing a 0-row row group, so the file must be metadata-only
            s3 = get_s3_client()
            with s3.open(result.file_uris[0], "rb") as f:
                empty_parquet = pq.ParquetFile(BytesIO(f.read()))
            assert empty_parquet.metadata.num_row_groups == 0
            assert empty_parquet.schema_arrow.names == ["id", "name"]

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


class _EmptyArrowClient:
    describe_body = b"id\tInt64\n"

    def __init__(self, schema: pa.Schema):
        self.schema = schema
        self.arrow_query_calls = 0
        self.schema_query_calls = 0
        self.describe_settings: dict[str, str] | None = None
        self.describe_query: str | None = None
        self.describe_calls: list[tuple[str, dict[str, str] | None]] = []
        self.reject_describe_with_settings = False
        self.arrow_query: str | None = None

    async def astream_query_as_arrow(
        self,
        query: str,
        *data: Any,
        query_parameters: dict[str, Any] | None = None,
        query_id: str | None = None,
        on_schema: Callable[[pa.Schema], None] | None = None,
    ) -> AsyncIterator[pa.RecordBatch]:
        self.arrow_query_calls += 1
        self.arrow_query = query
        if on_schema is not None:
            on_schema(self.schema)
        return
        yield  # type: ignore[unreachable]  # makes this an async generator that yields no batches

    @contextlib.asynccontextmanager
    async def apost_query(
        self,
        query: str,
        *data: Any,
        query_parameters: dict[str, Any] | None = None,
        query_id: str | None = None,
        settings: dict[str, str] | None = None,
    ) -> AsyncIterator[Any]:
        if query.startswith("DESCRIBE TABLE"):
            self.describe_calls.append((query, settings))
            if self.reject_describe_with_settings and settings is not None:
                raise ClickHouseError("Code: 8. DB::Exception: Cannot find column in source stream", query=query)
            self.describe_settings = settings
            self.describe_query = query
            body = self.describe_body
        else:
            self.schema_query_calls += 1
            buffer = pa.BufferOutputStream()
            with pa.ipc.new_stream(buffer, self.schema):
                pass
            body = buffer.getvalue().to_pybytes()

        class _Response:
            def __init__(self, response_body: bytes):
                self.content = self
                self.body = response_body

            async def read(self) -> bytes:
                return self.body

        yield _Response(body)


class TestHogqlTableEmptyResults:
    async def test_zero_row_query_uses_the_initial_stream_schema(self, ateam):
        client = _EmptyArrowClient(pa.schema([pa.field("id", pa.int64())]))

        @contextlib.asynccontextmanager
        async def fake_get_client(**kwargs):
            yield client

        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.materialize_view.get_clickhouse_client", fake_get_client
        ):
            batches = [batch async for batch in hogql_table("SELECT 1", ateam, LOGGER.bind())]

        assert len(batches) == 1
        assert batches[0][0].num_rows == 0
        assert client.arrow_query_calls == 1
        assert client.schema_query_calls == 0


class TestHogqlTableDescribeSettings:
    @pytest.mark.parametrize(
        "operator,global_function",
        [("IN", "globalIn("), ("NOT IN", "globalNotIn(")],
    )
    async def test_describe_probe_drops_global_subqueries(
        self, ateam: Team, operator: str, global_function: str
    ) -> None:
        client = _EmptyArrowClient(pa.schema([pa.field("distinct_id", pa.string())]))
        client.describe_body = b"distinct_id\tString\n"
        query = (
            f"SELECT distinct_id FROM events WHERE distinct_id {operator} "
            "(SELECT distinct_id FROM events WHERE event = 'x')"
        )

        @contextlib.asynccontextmanager
        async def fake_get_client(**kwargs: Any) -> AsyncIterator[_EmptyArrowClient]:
            yield client

        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.materialize_view.get_clickhouse_client", fake_get_client
        ):
            _ = [batch async for batch in hogql_table(query, ateam, LOGGER.bind())]

        assert client.describe_settings == {"distributed_product_mode": "allow", "prefer_global_in_and_join": "0"}
        assert client.describe_query is not None and global_function not in client.describe_query
        assert client.arrow_query is not None and global_function in client.arrow_query

    async def test_describe_probe_falls_back_to_the_untouched_query(self, ateam: Team) -> None:
        client = _EmptyArrowClient(pa.schema([pa.field("distinct_id", pa.string())]))
        client.describe_body = b"distinct_id\tString\n"
        client.reject_describe_with_settings = True
        query = "SELECT distinct_id FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE event = 'x')"

        @contextlib.asynccontextmanager
        async def fake_get_client(**kwargs: Any) -> AsyncIterator[_EmptyArrowClient]:
            yield client

        with unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.materialize_view.get_clickhouse_client", fake_get_client
        ):
            batches = [batch async for batch in hogql_table(query, ateam, LOGGER.bind())]

        assert [settings for _, settings in client.describe_calls] == [
            {"distributed_product_mode": "allow", "prefer_global_in_and_join": "0"},
            None,
        ]
        assert "globalIn(" in client.describe_calls[1][0]
        assert batches[0][1] == [("distinct_id", "String")]


class _SlowDescribeClient(_EmptyArrowClient):
    describe_body = b"ts\tDateTime\n"

    def __init__(self, schema: pa.Schema, describe_seconds: float):
        super().__init__(schema)
        self.describe_seconds = describe_seconds

    @contextlib.asynccontextmanager
    async def apost_query(
        self,
        query: str,
        *data: Any,
        query_parameters: dict[str, Any] | None = None,
        query_id: str | None = None,
        settings: dict[str, str] | None = None,
    ) -> AsyncIterator[Any]:
        await asyncio.sleep(self.describe_seconds)
        async with super().apost_query(
            query, *data, query_parameters=query_parameters, query_id=query_id, settings=settings
        ) as response:
            yield response


class TestHogqlTableResolutionDeadline:
    async def test_slow_describe_does_not_exhaust_the_resolution_deadline(self, ateam):
        # regression: a DateTime column sends hogql_table back through prepare_ast_for_printing to
        # wrap the select in toTimeZone. That second pass used to share the first pass's deadline
        # anchor, so a DESCRIBE slower than the deadline made it raise ResolutionTimeoutError.
        deadline_seconds = 1.0
        client = _SlowDescribeClient(
            pa.schema([pa.field("ts", pa.timestamp("us"))]), describe_seconds=deadline_seconds + 0.2
        )

        @contextlib.asynccontextmanager
        async def fake_get_client(**kwargs: Any) -> AsyncIterator[_SlowDescribeClient]:
            yield client

        def short_deadline_factory(view_name: str | None, **kwargs: Any) -> ResolverFactory:
            return bounded_resolver_factory_for_view(view_name, **{**kwargs, "deadline_seconds": deadline_seconds})

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.get_clickhouse_client", fake_get_client
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.bounded_resolver_factory_for_view",
                short_deadline_factory,
            ),
        ):
            batches = [batch async for batch in hogql_table("SELECT now() AS ts", ateam, LOGGER.bind())]

        assert [name for name, _ in batches[0][1]] == ["ts"]


class TestMaterializeViewStagesPersonPropertyRows:
    """A view feeding a warehouse property stages its projected rows as it writes, so the post-run sync
    reads only this run's rows instead of the whole table."""

    @staticmethod
    def _hogql_table(*args, **kwargs):
        del args, kwargs
        data = cast(
            Collection[pa.Array],
            [pa.array(["a", "b"], type=pa.string()), pa.array(["pro", "free"], type=pa.string())],
        )
        batch = pa.RecordBatch.from_arrays(data, names=["distinct_id", "plan"])

        async def async_generator():
            yield batch, [("distinct_id", "String"), ("plan", "String")]

        return async_generator()

    @contextlib.contextmanager
    def _env(self, bucket_name, projection):
        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_BUCKET=bucket_name,
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
                USE_LOCAL_SETUP=True,
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", self._hogql_table
            ),
            unittest.mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports."
                "pipelines.core.person_property_row_sink.person_property_projection_for",
                return_value=projection,
            ),
        ):
            yield

    async def test_stages_projected_columns_and_flags_the_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, adag, bucket_name, minio_client
    ):
        projection = [PersonPropertySourceProjection(key_column="distinct_id", columns=frozenset({"distinct_id"}))]
        inputs = MaterializeViewInputs(
            team_id=ateam.pk, dag_id=str(adag.id), node_id=str(anode.id), job_id=str(ajob.id)
        )
        with self._env(bucket_name, projection):
            result = await activity_environment.run(materialize_view_activity, inputs)
            # Resolved inside the overridden settings, so it names the same bucket the sink wrote to.
            prefix = person_property_job_staged_prefix(ateam.pk, saved_query_binding(asaved_query.id), str(ajob.id))

        # The workflow gates the person-property child on this field.
        assert result.person_property_sync_enabled is True

        listing = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix.removeprefix(f"{bucket_name}/"))
        keys = [obj["Key"] for obj in listing.get("Contents", [])]
        assert len(keys) == 1, f"expected one staged chunk under {prefix}, got {keys}"

        staged = await minio_client.get_object(Bucket=bucket_name, Key=keys[0])
        table = pq.read_table(BytesIO(await staged["Body"].read()))
        # Only the projected columns leave the pipeline — "plan" isn't mapped by this projection.
        assert table.column_names == ["distinct_id"]
        assert table.column("distinct_id").to_pylist() == ["a", "b"]

    async def test_unmapped_view_stages_nothing_and_leaves_the_flag_off(
        self, activity_environment, ateam, anode, ajob, adag, bucket_name, minio_client
    ):
        # The gate is what keeps an unmapped view (the vast majority) from paying for staging at all.
        inputs = MaterializeViewInputs(
            team_id=ateam.pk, dag_id=str(adag.id), node_id=str(anode.id), job_id=str(ajob.id)
        )
        with self._env(bucket_name, None):
            result = await activity_environment.run(materialize_view_activity, inputs)

        assert result.person_property_sync_enabled is False
        listing = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix="person_property_sync/")
        assert listing.get("Contents", []) == []


class TestMaterializeViewStagesAccountPropertyRows:
    @staticmethod
    def _hogql_table(*args, **kwargs):
        del args, kwargs
        data = cast(
            Collection[pa.Array],
            [pa.array(["org-1", "org-2"], type=pa.string()), pa.array([100.0, 200.0], type=pa.float64())],
        )
        batch = pa.RecordBatch.from_arrays(data, names=["organization_id", "mrr"])

        async def async_generator():
            yield batch, [("organization_id", "String"), ("mrr", "Float64")]

        return async_generator()

    async def test_exposes_account_delta_snapshot_without_staging_inside_materialization(
        self, activity_environment, ateam, anode, asaved_query, ajob, adag, bucket_name, minio_client
    ) -> None:
        projection = [
            AccountPropertySourceProjection(
                key_column="organization_id",
                columns=frozenset({"organization_id", "mrr"}),
            )
        ]
        inputs = MaterializeViewInputs(
            team_id=ateam.pk,
            dag_id=str(adag.id),
            node_id=str(anode.id),
            job_id=str(ajob.id),
        )
        with (
            override_settings(
                BUCKET_URL=f"s3://{bucket_name}",
                DATAWAREHOUSE_BUCKET=bucket_name,
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
                USE_LOCAL_SETUP=True,
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.hogql_table",
                self._hogql_table,
            ),
            unittest.mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports."
                "pipelines.core.account_property_row_sink.account_property_projection_for",
                return_value=projection,
            ),
        ):
            result = await activity_environment.run(materialize_view_activity, inputs)
            prefix = account_property_job_staged_prefix(
                ateam.pk,
                saved_query_binding(asaved_query.id),
                str(ajob.id),
            )
            listing_before_staging = await minio_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix.removeprefix(f"{bucket_name}/"),
            )
            assert result.delta_version is not None
            activity_environment.info = replace(activity_environment.info, workflow_run_id=str(uuid4()))
            staged = await activity_environment.run(
                stage_warehouse_account_property_files_activity,
                StageAccountPropertySyncInput(
                    team_id=ateam.pk,
                    saved_query_id=str(asaved_query.id),
                    job_id=str(ajob.id),
                    table_uri=result.table_uri,
                    delta_version=result.delta_version,
                ),
            )
            listing_after_staging = await minio_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix.removeprefix(f"{bucket_name}/"),
            )

        assert result.account_property_sync_enabled is True
        assert listing_before_staging.get("Contents", []) == []
        assert staged is True
        keys = [obj["Key"] for obj in listing_after_staging.get("Contents", [])]
        assert len(keys) == 1
        staged_object = await minio_client.get_object(Bucket=bucket_name, Key=keys[0])
        table = pq.read_table(BytesIO(await staged_object["Body"].read()))
        assert table.column_names == ["mrr", "organization_id"]
