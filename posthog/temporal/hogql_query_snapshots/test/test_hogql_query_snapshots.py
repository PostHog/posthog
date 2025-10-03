import uuid
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from django.conf import settings
from django.db.models import QuerySet

import pyarrow as pa
import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.hogql_query_snapshots.backup import create_backup_object
from posthog.temporal.hogql_query_snapshots.delta_snapshot import DeltaSnapshot
from posthog.temporal.hogql_query_snapshots.run_workflow import (
    CreateBackupSnapshotJobInputs,
    CreateSnapshotJobInputs,
    FinishSnapshotJobInputs,
    RestoreFromBackupInputs,
    RunSnapshotActivityInputs,
    RunWorkflow,
    RunWorkflowInputs,
    create_backup_snapshot_job_activity,
    create_snapshot_job_activity,
    finish_snapshot_job_activity,
    restore_from_backup_activity,
    run_snapshot_activity,
    validate_snapshot_schema,
)
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.snapshot_config import DataWarehouseSnapshotConfig
from posthog.warehouse.models.snapshot_job import DataWarehouseSnapshotJob
from posthog.warehouse.models.table import DataWarehouseTable

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest_asyncio.fixture
async def credential(ateam):
    """Create a test data warehouse credential."""
    return await sync_to_async(DataWarehouseCredential.objects.create)(
        team=ateam,
        access_key=settings.AIRBYTE_BUCKET_KEY or "test_key",
        access_secret=settings.AIRBYTE_BUCKET_SECRET or "test_secret",
    )


@pytest_asyncio.fixture
async def saved_query(ateam, auser, credential):
    """Create a test saved query with snapshot configuration."""

    # Create the saved query
    saved_query = await sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="test_snapshot_query",
        query={
            "kind": "HogQLQuery",
            "query": "SELECT id, name, created_at FROM events ORDER BY id",
        },
        created_by=auser,
        type=DataWarehouseSavedQuery.Type.VIEW,
        snapshot_enabled=True,
    )

    # Create the snapshot configuration
    await sync_to_async(DataWarehouseSnapshotConfig.objects.create)(
        team=ateam,
        saved_query=saved_query,
        merge_key="id",
        fields=["id", "name", "created_at"],
        timestamp_field="created_at",
    )

    # Create a mock source table for the query to reference
    source_table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name="some_table_to_snapshot",
        credential=credential,
        format=DataWarehouseTable.TableFormat.Parquet,
        url_pattern="https://example.com/events/*.parquet",
        row_count=1000,
        size_in_s3_mib=50,
    )

    saved_query.table = source_table
    await sync_to_async(saved_query.save)()

    return saved_query


@pytest.mark.asyncio
async def test_create_snapshot_job_activity(ateam, saved_query):
    """Test the create_snapshot_job_activity creates a job correctly."""

    inputs = CreateSnapshotJobInputs(
        team_id=ateam.id,
        saved_query_id=str(saved_query.id),
    )

    # Mock the temporal activity info
    with patch("temporalio.activity.info") as mock_info:
        mock_info.return_value.workflow_id = "test-workflow-123"
        mock_info.return_value.workflow_run_id = "test-run-456"

        job_id, _ = await create_snapshot_job_activity(inputs)

    # Verify job was created
    assert job_id is not None
    job = await sync_to_async(DataWarehouseSnapshotJob.objects.get)(id=job_id)
    assert job.team_id == ateam.id
    assert job.status == DataWarehouseSnapshotJob.Status.RUNNING
    assert job.workflow_id == "test-workflow-123"
    assert job.workflow_run_id == "test-run-456"


@pytest.mark.asyncio
async def test_run_snapshot_activity_success(ateam, saved_query):
    """Test the run_snapshot_activity creates a snapshot successfully."""

    inputs = RunSnapshotActivityInputs(
        team_id=ateam.id,
        saved_query_id=str(saved_query.id),
    )

    # Mock the HogQL execution to return test data
    async def mock_hogql_table(query, *args, **kwargs):
        # The query will be the constructed HogQL with added columns
        # Return data that includes all the added columns the query expects
        result_data = pa.RecordBatch.from_pydict(
            {
                "id": [1, 2, 3],
                "name": ["Event A", "Event B", "Event C"],
                "created_at": [datetime.now(UTC), datetime.now(UTC), datetime.now(UTC)],
                "_ph_merge_key": [1, 2, 3],  # merge_key column added by query
                "_ph_row_hash": ["hash1", "hash2", "hash3"],  # row hash added by query
                "_ph_snapshot_ts": [datetime.now(UTC)] * 3,  # snapshot timestamp added by query
            }
        )
        yield (
            result_data,
            [
                ("id", "Uint8"),
                ("name", "String"),
                ("created_at", "DateTime64(6, 'UTC')"),
                ("_ph_merge_key", "UInt64"),
                ("_ph_row_hash", "String"),
                ("_ph_snapshot_ts", "Nullable(DateTime64(6, 'UTC'))"),
            ],
        )

    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table):
        snapshot_ts, snapshot_table_id = await run_snapshot_activity(inputs)

    # Verify results
    assert snapshot_ts is not None
    assert snapshot_table_id is not None

    # Verify snapshot table was created
    snapshot_table = await sync_to_async(DataWarehouseTable.objects.get)(id=snapshot_table_id)
    assert snapshot_table.name == saved_query.normalized_name
    assert snapshot_table.type == DataWarehouseTable.Type.SNAPSHOT
    assert snapshot_table.format == DataWarehouseTable.TableFormat.DeltaS3Wrapper

    # Verify delta table was created in S3
    delta_snapshot = DeltaSnapshot(saved_query)
    delta_table = delta_snapshot.get_delta_table()
    assert delta_table is not None

    # Verify the table contains our test data
    df = delta_table.to_pandas()
    assert len(df) == 3
    assert set(df["id"].tolist()) == {1, 2, 3}
    assert "_ph_merge_key" in df.columns
    assert "_ph_row_hash" in df.columns
    assert "_ph_snapshot_ts" in df.columns
    assert "_ph_valid_until" in df.columns


@pytest.mark.asyncio
async def test_finish_snapshot_job_activity_success(ateam, saved_query, auser):
    """Test the finish_snapshot_job_activity completes successfully."""

    # Create a snapshot job
    job = await sync_to_async(DataWarehouseSnapshotJob.objects.create)(
        team=ateam,
        config=saved_query.datawarehousesnapshotconfig,
        status=DataWarehouseSnapshotJob.Status.RUNNING,
        workflow_id="test-workflow",
        workflow_run_id="test-run",
        created_by=auser,
    )

    # Create a mock snapshot table
    snapshot_table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name=saved_query.normalized_name,
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern=f"s3://test/{saved_query.snapshot_folder_path}/",
        type=DataWarehouseTable.Type.SNAPSHOT,
    )

    snapshot_ts = "2024-01-01 12:00:00.123456"

    inputs = FinishSnapshotJobInputs(
        team_id=ateam.id,
        job_id=str(job.id),
        error=None,
        snapshot_ts=snapshot_ts,
        snapshot_table_id=str(snapshot_table.id),
        saved_query_id=str(saved_query.id),
    )
    with patch(
        "posthog.warehouse.models.datawarehouse_saved_query.DataWarehouseSavedQuery.get_columns"
    ) as mock_get_columns:
        mock_get_columns.return_value = {
            "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
            "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
            "created_at": {"clickhouse": "DateTime64(6, 'UTC')", "hogql": "DateTimeDatabaseField", "valid": True},
        }
        await finish_snapshot_job_activity(inputs)

    # Verify job status was updated
    job = await sync_to_async(DataWarehouseSnapshotJob.objects.prefetch_related("saved_query").get)(id=job.id)
    assert job.status == DataWarehouseSnapshotJob.Status.COMPLETED
    assert job.error is None

    # Verify a snapshot saved query was created
    snapshot_saved_query: DataWarehouseSavedQuery | None = job.saved_query
    assert isinstance(snapshot_saved_query, DataWarehouseSavedQuery)
    assert snapshot_saved_query.type == DataWarehouseSavedQuery.Type.SNAPSHOT
    assert snapshot_saved_query.name == f"{snapshot_table.name}_2024_01_01_12_00_00_123456"

    assert f"_ph_snapshot_ts <= toDateTime('{snapshot_ts}', 'UTC')" in snapshot_saved_query.query["query"]


@pytest.mark.asyncio
async def test_finish_snapshot_job_activity_with_error(ateam, saved_query, auser):
    """Test the finish_snapshot_job_activity handles errors correctly."""

    # Create a snapshot job
    job = await sync_to_async(DataWarehouseSnapshotJob.objects.create)(
        team=ateam,
        config=saved_query.datawarehousesnapshotconfig,
        status=DataWarehouseSnapshotJob.Status.RUNNING,
        workflow_id="test-workflow",
        workflow_run_id="test-run",
        created_by=auser,
    )

    error_message = "Test error occurred"

    inputs = FinishSnapshotJobInputs(
        team_id=ateam.id,
        job_id=str(job.id),
        error=error_message,
        snapshot_ts=None,
        snapshot_table_id=None,
        saved_query_id=str(saved_query.id),
    )

    await finish_snapshot_job_activity(inputs)

    # Verify job status was updated with error
    await sync_to_async(job.refresh_from_db)()
    assert job.status == DataWarehouseSnapshotJob.Status.FAILED
    assert job.error == error_message
    assert job.saved_query is None


@pytest.mark.asyncio
async def test_full_workflow_success(ateam, saved_query):
    """Test the complete end-to-end workflow execution."""

    # Mock the HogQL execution to return test data
    async def mock_hogql_table(query, *args, **kwargs):
        # Return data that includes all the columns the constructed query expects
        result_data = pa.RecordBatch.from_pydict(
            {
                "id": [1, 2, 3, 4, 5],
                "name": ["Event A", "Event B", "Event C", "Event D", "Event E"],
                "created_at": [datetime.now(UTC)] * 5,
                "_ph_merge_key": [1, 2, 3, 4, 5],
                "_ph_row_hash": ["hash1", "hash2", "hash3", "hash4", "hash5"],
                "_ph_snapshot_ts": [datetime.now(UTC)] * 5,
            }
        )
        yield (
            result_data,
            [
                ("id", "Uint8"),
                ("name", "String"),
                ("created_at", "DateTime64(6, 'UTC')"),
                ("_ph_merge_key", "UInt64"),
                ("_ph_row_hash", "String"),
                ("_ph_snapshot_ts", "Nullable(DateTime64(6, 'UTC'))"),
            ],
        )

    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table):
        with patch("temporalio.activity.info") as mock_info:
            with patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
                with patch(
                    "posthog.warehouse.models.datawarehouse_saved_query.DataWarehouseSavedQuery.get_columns"
                ) as mock_get_columns_saved_query:
                    mock_get_columns.return_value = {
                        "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
                        "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                        "created_at": {
                            "clickhouse": "DateTime64(6, 'UTC')",
                            "hogql": "DateTimeDatabaseField",
                            "valid": True,
                        },
                        "_ph_merge_key": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                        "_ph_row_hash": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                        "_ph_snapshot_ts": {
                            "clickhouse": "DateTime64(6, 'UTC')",
                            "hogql": "DateTimeDatabaseField",
                            "valid": True,
                        },
                        "_ph_valid_until": {
                            "clickhouse": "Nullable(DateTime64(6, 'UTC'))",
                            "hogql": "DateTimeDatabaseField",
                            "valid": True,
                        },
                    }

                    mock_get_columns_saved_query.return_value = {
                        "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
                        "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                        "created_at": {
                            "clickhouse": "DateTime64(6, 'UTC')",
                            "hogql": "DateTimeDatabaseField",
                            "valid": True,
                        },
                        "_ph_merge_key": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                        "_ph_row_hash": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                        "_ph_snapshot_ts": {
                            "clickhouse": "DateTime64(6, 'UTC')",
                            "hogql": "DateTimeDatabaseField",
                            "valid": True,
                        },
                        "_ph_valid_until": {
                            "clickhouse": "Nullable(DateTime64(6, 'UTC'))",
                            "hogql": "DateTimeDatabaseField",
                            "valid": True,
                        },
                    }

                    mock_info.return_value.workflow_id = "test-workflow-full"
                    mock_info.return_value.workflow_run_id = "test-run-full"

                    workflow_id = str(uuid.uuid4())
                    inputs = RunWorkflowInputs(
                        team_id=ateam.id,
                        saved_query_id=str(saved_query.id),
                    )

                    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                        async with Worker(
                            activity_environment.client,
                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                            workflows=[RunWorkflow],
                            activities=[
                                create_snapshot_job_activity,
                                run_snapshot_activity,
                                finish_snapshot_job_activity,
                            ],
                            workflow_runner=UnsandboxedWorkflowRunner(),
                        ):
                            await activity_environment.client.execute_workflow(
                                RunWorkflow.run,
                                inputs,
                                id=workflow_id,
                                task_queue=settings.TEMPORAL_TASK_QUEUE,
                                retry_policy=RetryPolicy(maximum_attempts=1),
                                execution_timeout=timedelta(minutes=5),
                            )

    # Verify workflow completed successfully
    jobs_filtered: QuerySet = await sync_to_async(
        DataWarehouseSnapshotJob.objects.prefetch_related("saved_query").filter
    )(team=ateam, config=saved_query.datawarehousesnapshotconfig)
    jobs: list[DataWarehouseSnapshotJob] = await sync_to_async(list)(jobs_filtered)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == DataWarehouseSnapshotJob.Status.COMPLETED
    assert job.error is None
    assert job.saved_query is not None

    # Verify snapshot table exists
    snapshot_table = await sync_to_async(
        DataWarehouseTable.objects.filter(
            team=ateam, name=saved_query.normalized_name, type=DataWarehouseTable.Type.SNAPSHOT
        ).first
    )()
    assert snapshot_table is not None

    # Verify delta table was created in S3 with correct data
    delta_snapshot = DeltaSnapshot(saved_query)
    delta_table = delta_snapshot.get_delta_table()
    assert delta_table is not None

    df = delta_table.to_pandas()
    assert len(df) == 5
    assert set(df["id"].tolist()) == {1, 2, 3, 4, 5}

    # Verify snapshot metadata columns
    required_columns = ["_ph_merge_key", "_ph_row_hash", "_ph_snapshot_ts", "_ph_valid_until"]
    for col in required_columns:
        assert col in df.columns

    # All records should be active (valid_until is NULL)
    assert df["_ph_valid_until"].isna().all()


@pytest.mark.asyncio
async def test_workflow_failure_handling(ateam, saved_query):
    """Test workflow handles failures correctly."""

    # Mock HogQL execution to raise an exception
    async def mock_failing_hogql_table(*args, **kwargs):
        yield None, None

    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_failing_hogql_table):
        with patch("temporalio.activity.info") as mock_info:
            mock_info.return_value.workflow_id = "test-workflow-fail"
            mock_info.return_value.workflow_run_id = "test-run-fail"

            workflow_id = str(uuid.uuid4())
            inputs = RunWorkflowInputs(
                team_id=ateam.id,
                saved_query_id=str(saved_query.id),
            )
            # Expect workflow to fail
            with pytest.raises(Exception):
                async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                    async with Worker(
                        activity_environment.client,
                        task_queue=settings.TEMPORAL_TASK_QUEUE,
                        workflows=[RunWorkflow],
                        activities=[
                            create_snapshot_job_activity,
                            run_snapshot_activity,
                            finish_snapshot_job_activity,
                        ],
                        workflow_runner=UnsandboxedWorkflowRunner(),
                    ):
                        await activity_environment.client.execute_workflow(
                            RunWorkflow.run,
                            inputs,
                            id=workflow_id,
                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            execution_timeout=timedelta(minutes=5),
                        )

    # Verify job was marked as failed
    jobs_filtered: QuerySet = await sync_to_async(
        DataWarehouseSnapshotJob.objects.prefetch_related("saved_query").filter
    )(team=ateam, config=saved_query.datawarehousesnapshotconfig)
    jobs: list[DataWarehouseSnapshotJob] = await sync_to_async(list)(jobs_filtered)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == DataWarehouseSnapshotJob.Status.FAILED
    assert "AttributeError: 'NoneType' object has no attribute 'schema'" in str(job.error)
    assert job.saved_query is None


@pytest.mark.asyncio
async def test_snapshot_incremental_updates(ateam, saved_query):
    """Test that incremental snapshots work correctly with deltas."""

    # First snapshot with initial data
    async def mock_initial_hogql_table(query, *args, **kwargs):
        result_data = pa.RecordBatch.from_pydict(
            {
                "id": [1, 2, 3],
                "name": ["Event A", "Event B", "Event C"],
                "created_at": [datetime.now(UTC)] * 3,
                "_ph_merge_key": [1, 2, 3],
                "_ph_row_hash": ["hash1", "hash2", "hash3"],
                "_ph_snapshot_ts": [datetime.now(UTC)] * 3,
            }
        )
        yield (
            result_data,
            [
                ("id", "Uint8"),
                ("name", "String"),
                ("created_at", "DateTime64(6, 'UTC')"),
                ("_ph_merge_key", "UInt64"),
                ("_ph_row_hash", "String"),
                ("_ph_snapshot_ts", "Nullable(DateTime64(6, 'UTC'))"),
            ],
        )

    inputs = RunSnapshotActivityInputs(
        team_id=ateam.id,
        saved_query_id=str(saved_query.id),
    )

    # Run first snapshot
    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_initial_hogql_table):
        await run_snapshot_activity(inputs)

    # Verify initial data
    delta_snapshot = DeltaSnapshot(saved_query)
    delta_table = delta_snapshot.get_delta_table()
    assert delta_table is not None
    initial_df = delta_table.to_pandas()
    assert len(initial_df) == 3

    # Second snapshot with updated data (update record 2, add record 4, remove record 3)
    async def mock_updated_hogql_table(query, *args, **kwargs):
        result_data = pa.RecordBatch.from_pydict(
            {
                "id": [1, 2, 4],
                "name": ["Event A", "Event B Updated", "Event D"],
                "created_at": [datetime.now(UTC)] * 3,
                "_ph_merge_key": [1, 2, 4],
                "_ph_row_hash": ["hash1_v2", "hash2_v2", "hash4"],
                "_ph_snapshot_ts": [datetime.now(UTC)] * 3,
            }
        )
        yield (
            result_data,
            [
                ("id", "Uint8"),
                ("name", "String"),
                ("created_at", "DateTime64(6, 'UTC')"),
                ("_ph_merge_key", "UInt64"),
                ("_ph_row_hash", "String"),
                ("_ph_snapshot_ts", "Nullable(DateTime64(6, 'UTC'))"),
            ],
        )

    # Run second snapshot
    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_updated_hogql_table):
        await run_snapshot_activity(inputs)

    # Verify incremental updates
    delta_table = delta_snapshot.get_delta_table()
    final_df = delta_table.to_pandas()

    # Should have historical records for all changes
    assert len(final_df) >= 4  # At least original records + updates

    # Verify current active records (where _ph_valid_until is NULL)
    active_df = final_df[final_df["_ph_valid_until"].isna()]
    assert len(active_df) == 3
    assert set(active_df["id"].tolist()) == {1, 2, 4}

    # Verify record 2 was updated
    record_2 = active_df[active_df["id"] == 2]
    assert len(record_2) == 1
    assert record_2.iloc[0]["name"] == "Event B Updated"

    # Verify record 3 is marked as deleted (has _ph_valid_until)
    historical_df = final_df[final_df["_ph_valid_until"].notna()]
    deleted_record_3 = historical_df[historical_df["id"] == 3]
    assert len(deleted_record_3) >= 1  # Should exist in historical records


@pytest.mark.asyncio
async def test_create_backup_snapshot_job_activity(ateam, saved_query):
    """Test the create_backup_snapshot_job_activity creates a backup correctly."""

    inputs = CreateBackupSnapshotJobInputs(
        team_id=ateam.id,
        saved_query_id=str(saved_query.id),
    )

    with patch("posthog.temporal.hogql_query_snapshots.run_workflow.create_backup_object") as mock_create_backup:
        await create_backup_snapshot_job_activity(inputs)

    # Verify backup creation was called with the correct saved query
    mock_create_backup.assert_called_once()
    called_saved_query = mock_create_backup.call_args[0][0]
    assert called_saved_query.id == saved_query.id
    assert called_saved_query.team_id == ateam.id


@pytest.mark.asyncio
async def test_restore_from_backup_activity(ateam, saved_query):
    """Test the restore_from_backup_activity restores from backup correctly."""

    inputs = RestoreFromBackupInputs(
        team_id=ateam.id,
        saved_query_id=str(saved_query.id),
    )

    with patch("posthog.temporal.hogql_query_snapshots.run_workflow.restore_from_backup") as mock_restore_backup:
        await restore_from_backup_activity(inputs)

    # Verify restore was called with the correct saved query
    mock_restore_backup.assert_called_once()
    called_saved_query = mock_restore_backup.call_args[0][0]
    assert called_saved_query.id == saved_query.id
    assert called_saved_query.team_id == ateam.id


@pytest.mark.asyncio
async def test_backup_lifecycle_workflow_failure_and_restore(ateam, saved_query):
    """Test that backup files are created and restored on workflow failure."""

    # Track backup operations
    backup_created = False
    backup_restored = False
    backup_cleared = False

    def mock_create_backup(saved_query_arg):
        nonlocal backup_created
        backup_created = True

        create_backup_object(saved_query_arg)

    def mock_restore_backup(saved_query_arg):
        nonlocal backup_restored
        backup_restored = True
        from posthog.temporal.hogql_query_snapshots.backup import restore_from_backup

        restore_from_backup(saved_query_arg)

    def mock_clear_backup(saved_query_arg):
        nonlocal backup_cleared
        backup_cleared = True

        from posthog.temporal.hogql_query_snapshots.backup import clear_backup_object

        clear_backup_object(saved_query_arg)

    # Mock HogQL execution to fail
    async def mock_hogql_table(query, *args, **kwargs):
        result_data = pa.RecordBatch.from_pydict(
            {
                "id": [1, 2, 3],
                "name": ["Event A", "Event B", "Event C"],
                "created_at": [datetime.now(UTC)] * 3,
                "_ph_merge_key": [1, 2, 3],
                "_ph_row_hash": ["hash1", "hash2", "hash3"],
                "_ph_snapshot_ts": [datetime.now(UTC)] * 3,
            }
        )
        yield (
            result_data,
            [
                ("id", "Uint8"),
                ("name", "String"),
                ("created_at", "DateTime64(6, 'UTC')"),
                ("_ph_merge_key", "UInt64"),
                ("_ph_row_hash", "String"),
                ("_ph_snapshot_ts", "Nullable(DateTime64(6, 'UTC'))"),
            ],
        )

    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table):
        with patch("temporalio.activity.info") as mock_info:
            with patch("posthog.temporal.hogql_query_snapshots.run_workflow.create_backup_object", mock_create_backup):
                with patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
                    with patch(
                        "posthog.warehouse.models.datawarehouse_saved_query.DataWarehouseSavedQuery.get_columns"
                    ) as mock_get_columns_saved_query:
                        with patch(
                            "posthog.temporal.hogql_query_snapshots.run_workflow.restore_from_backup",
                            mock_restore_backup,
                        ):
                            with patch(
                                "posthog.temporal.hogql_query_snapshots.run_workflow.clear_backup_object",
                                mock_clear_backup,
                            ):
                                # Setup mocks
                                mock_get_columns.return_value = {
                                    "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
                                    "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                                    "created_at": {
                                        "clickhouse": "DateTime64(6, 'UTC')",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_merge_key": {
                                        "clickhouse": "String",
                                        "hogql": "StringDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_row_hash": {
                                        "clickhouse": "String",
                                        "hogql": "StringDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_snapshot_ts": {
                                        "clickhouse": "DateTime64(6, 'UTC')",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_valid_until": {
                                        "clickhouse": "Nullable(DateTime64(6, 'UTC'))",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                }
                                mock_get_columns_saved_query.return_value = mock_get_columns.return_value

                                mock_info.return_value.workflow_id = f"test-workflow-backup-success"
                                mock_info.return_value.workflow_run_id = f"test-run-backup-success"

                                workflow_id = str(uuid.uuid4())
                                inputs = RunWorkflowInputs(
                                    team_id=ateam.id,
                                    saved_query_id=str(saved_query.id),
                                )

                                async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                                    async with Worker(
                                        activity_environment.client,
                                        task_queue=settings.TEMPORAL_TASK_QUEUE,
                                        workflows=[RunWorkflow],
                                        activities=[
                                            create_snapshot_job_activity,
                                            create_backup_snapshot_job_activity,
                                            run_snapshot_activity,
                                            restore_from_backup_activity,
                                            finish_snapshot_job_activity,
                                        ],
                                        workflow_runner=UnsandboxedWorkflowRunner(),
                                    ):
                                        await activity_environment.client.execute_workflow(
                                            RunWorkflow.run,
                                            inputs,
                                            id=workflow_id,
                                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                                            retry_policy=RetryPolicy(maximum_attempts=1),
                                            execution_timeout=timedelta(minutes=5),
                                        )

    # Mock HogQL execution to fail
    async def mock_failing_hogql_table(query, *args, **kwargs):
        yield None, None

    with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_failing_hogql_table):
        with patch("temporalio.activity.info") as mock_info:
            with patch("posthog.temporal.hogql_query_snapshots.run_workflow.create_backup_object", mock_create_backup):
                with patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
                    with patch(
                        "posthog.warehouse.models.datawarehouse_saved_query.DataWarehouseSavedQuery.get_columns"
                    ) as mock_get_columns_saved_query:
                        with patch(
                            "posthog.temporal.hogql_query_snapshots.run_workflow.restore_from_backup",
                            mock_restore_backup,
                        ):
                            with patch(
                                "posthog.temporal.hogql_query_snapshots.run_workflow.clear_backup_object",
                                mock_clear_backup,
                            ):
                                # Setup mocks
                                mock_get_columns.return_value = {
                                    "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
                                    "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                                    "created_at": {
                                        "clickhouse": "DateTime64(6, 'UTC')",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_merge_key": {
                                        "clickhouse": "String",
                                        "hogql": "StringDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_row_hash": {
                                        "clickhouse": "String",
                                        "hogql": "StringDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_snapshot_ts": {
                                        "clickhouse": "DateTime64(6, 'UTC')",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_valid_until": {
                                        "clickhouse": "Nullable(DateTime64(6, 'UTC'))",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                }
                                mock_get_columns_saved_query.return_value = mock_get_columns.return_value

                                mock_info.return_value.workflow_id = f"test-workflow-backup-fail"
                                mock_info.return_value.workflow_run_id = f"test-run-backup-fail"

                                workflow_id = str(uuid.uuid4())
                                inputs = RunWorkflowInputs(
                                    team_id=ateam.id,
                                    saved_query_id=str(saved_query.id),
                                )

                                with pytest.raises(Exception):
                                    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                                        async with Worker(
                                            activity_environment.client,
                                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                                            workflows=[RunWorkflow],
                                            activities=[
                                                create_snapshot_job_activity,
                                                create_backup_snapshot_job_activity,
                                                run_snapshot_activity,
                                                restore_from_backup_activity,
                                                finish_snapshot_job_activity,
                                            ],
                                            workflow_runner=UnsandboxedWorkflowRunner(),
                                        ):
                                            await activity_environment.client.execute_workflow(
                                                RunWorkflow.run,
                                                inputs,
                                                id=workflow_id,
                                                task_queue=settings.TEMPORAL_TASK_QUEUE,
                                                retry_policy=RetryPolicy(maximum_attempts=1),
                                                execution_timeout=timedelta(minutes=5),
                                            )

    # Verify backup lifecycle on failure
    assert backup_created, "Backup should have been created during workflow execution"
    assert backup_restored, "Backup should have been restored after workflow failure"
    assert backup_cleared, "Backup should have been cleared even after failure in finally block"

    # Verify job was marked as failed
    jobs_filtered: QuerySet = await sync_to_async(
        DataWarehouseSnapshotJob.objects.prefetch_related("saved_query").filter
    )(team=ateam, config=saved_query.datawarehousesnapshotconfig)
    jobs: list[DataWarehouseSnapshotJob] = await sync_to_async(list)(jobs_filtered)
    assert len(jobs) == 2
    job = jobs[1]
    assert job.status == DataWarehouseSnapshotJob.Status.FAILED


@pytest.mark.asyncio
async def test_backup_lifecycle_multiple_workflow_runs(ateam, saved_query):
    """Test backup lifecycle across multiple workflow runs."""

    # Mock the HogQL execution to return test data
    async def mock_hogql_table(query, *args, **kwargs):
        result_data = pa.RecordBatch.from_pydict(
            {
                "id": [1, 2, 3],
                "name": ["Event A", "Event B", "Event C"],
                "created_at": [datetime.now(UTC)] * 3,
                "_ph_merge_key": [1, 2, 3],
                "_ph_row_hash": ["hash1", "hash2", "hash3"],
                "_ph_snapshot_ts": [datetime.now(UTC)] * 3,
            }
        )
        yield (
            result_data,
            [
                ("id", "Uint8"),
                ("name", "String"),
                ("created_at", "DateTime64(6, 'UTC')"),
                ("_ph_merge_key", "UInt64"),
                ("_ph_row_hash", "String"),
                ("_ph_snapshot_ts", "Nullable(DateTime64(6, 'UTC'))"),
            ],
        )

    # Track backup operations across runs
    backup_operations = []

    def mock_create_backup(saved_query_arg):
        backup_operations.append("create")

        create_backup_object(saved_query_arg)

    def mock_clear_backup(saved_query_arg):
        backup_operations.append("clear")

        from posthog.temporal.hogql_query_snapshots.backup import clear_backup_object

        clear_backup_object(saved_query_arg)

    # Run workflow twice
    for run_num in range(2):
        with patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table):
            with patch("temporalio.activity.info") as mock_info:
                with patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
                    with patch(
                        "posthog.warehouse.models.datawarehouse_saved_query.DataWarehouseSavedQuery.get_columns"
                    ) as mock_get_columns_saved_query:
                        with patch(
                            "posthog.temporal.hogql_query_snapshots.run_workflow.create_backup_object",
                            mock_create_backup,
                        ):
                            with patch(
                                "posthog.temporal.hogql_query_snapshots.run_workflow.clear_backup_object",
                                mock_clear_backup,
                            ):
                                # Setup mocks
                                mock_get_columns.return_value = {
                                    "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
                                    "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                                    "created_at": {
                                        "clickhouse": "DateTime64(6, 'UTC')",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_merge_key": {
                                        "clickhouse": "String",
                                        "hogql": "StringDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_row_hash": {
                                        "clickhouse": "String",
                                        "hogql": "StringDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_snapshot_ts": {
                                        "clickhouse": "DateTime64(6, 'UTC')",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                    "_ph_valid_until": {
                                        "clickhouse": "Nullable(DateTime64(6, 'UTC'))",
                                        "hogql": "DateTimeDatabaseField",
                                        "valid": True,
                                    },
                                }
                                mock_get_columns_saved_query.return_value = mock_get_columns.return_value

                                mock_info.return_value.workflow_id = f"test-workflow-backup-multi-{run_num}"
                                mock_info.return_value.workflow_run_id = f"test-run-backup-multi-{run_num}"

                                workflow_id = str(uuid.uuid4())
                                inputs = RunWorkflowInputs(
                                    team_id=ateam.id,
                                    saved_query_id=str(saved_query.id),
                                )

                                async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                                    async with Worker(
                                        activity_environment.client,
                                        task_queue=settings.TEMPORAL_TASK_QUEUE,
                                        workflows=[RunWorkflow],
                                        activities=[
                                            create_snapshot_job_activity,
                                            create_backup_snapshot_job_activity,
                                            run_snapshot_activity,
                                            finish_snapshot_job_activity,
                                        ],
                                        workflow_runner=UnsandboxedWorkflowRunner(),
                                    ):
                                        await activity_environment.client.execute_workflow(
                                            RunWorkflow.run,
                                            inputs,
                                            id=workflow_id,
                                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                                            retry_policy=RetryPolicy(maximum_attempts=1),
                                            execution_timeout=timedelta(minutes=5),
                                        )

    # Verify backup operations happened correctly for both runs
    expected_operations = ["clear", "create", "clear"]
    assert backup_operations == expected_operations, f"Expected {expected_operations}, got {backup_operations}"

    # Verify both workflows completed successfully
    jobs_filtered: QuerySet = await sync_to_async(
        DataWarehouseSnapshotJob.objects.prefetch_related("saved_query").filter
    )(team=ateam, config=saved_query.datawarehousesnapshotconfig)
    jobs: list[DataWarehouseSnapshotJob] = await sync_to_async(list)(jobs_filtered)
    assert len(jobs) == 2
    for job in jobs:
        assert job.status == DataWarehouseSnapshotJob.Status.COMPLETED
        assert job.error is None


@pytest.mark.asyncio
async def test_validate_snapshot_schema(ateam, saved_query):
    """Test schema validation and table creation."""

    schema_dict = {
        "id": "Int64",
        "name": "String",
        "created_at": "DateTime64(6)",
        "_ph_merge_key": "String",
        "_ph_row_hash": "String",
        "_ph_snapshot_ts": "DateTime64(6)",
        "_ph_valid_until": "Nullable(DateTime64(6))",
    }

    with patch("posthog.temporal.hogql_query_snapshots.run_workflow.LOGGER") as logger_mock:
        with patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns") as get_columns_mock:
            get_columns_mock.return_value = {
                "id": {"clickhouse": "UInt64", "hogql": "IntegerDatabaseField", "valid": True},
                "name": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                "created_at": {"clickhouse": "DateTime64(6, 'UTC')", "hogql": "DateTimeDatabaseField", "valid": True},
                "_ph_merge_key": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                "_ph_row_hash": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                "_ph_snapshot_ts": {
                    "clickhouse": "DateTime64(6, 'UTC')",
                    "hogql": "DateTimeDatabaseField",
                    "valid": True,
                },
                "_ph_valid_until": {
                    "clickhouse": "Nullable(DateTime64(6, 'UTC'))",
                    "hogql": "DateTimeDatabaseField",
                    "valid": True,
                },
            }
            table_id = await sync_to_async(validate_snapshot_schema)(
                ateam.id,
                saved_query,
                logger_mock,
                schema_dict,
            )

    assert table_id is not None

    # Verify table was created with correct properties
    table = await sync_to_async(DataWarehouseTable.objects.get)(id=table_id)
    assert table.team_id == ateam.id
    assert table.name == saved_query.normalized_name
    assert table.type == DataWarehouseTable.Type.SNAPSHOT
    assert table.format == DataWarehouseTable.TableFormat.DeltaS3Wrapper

    # Verify columns were set correctly
    assert table.columns is not None
    for col_name, expected_hogql_type in schema_dict.items():
        if col_name in table.columns:
            assert table.columns[col_name]["hogql"] == expected_hogql_type
