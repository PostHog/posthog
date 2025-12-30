from collections.abc import Collection
from typing import cast

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
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
from posthog.temporal.data_modeling.activities.materialize_view import InvalidNodeTypeException

from products.data_modeling.backend.models import Node, NodeType
from products.data_warehouse.backend.models import DataModelingJob, DataWarehouseSavedQuery, DataWarehouseTable

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
async def anode(ateam, saved_query):
    node = await database_sync_to_async(Node.objects.create)(
        team=ateam,
        saved_query=saved_query,
        dag_id="test-dag",
        name="test_model",
        type=NodeType.MAT_VIEW,
    )
    yield node
    await database_sync_to_async(node.delete)()


@pytest_asyncio.fixture
async def ajob(ateam, saved_query):
    job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id="test-workflow",
    )
    yield job
    await database_sync_to_async(job.delete)()


class TestCreateDataModelingJobActivity:
    async def test_creates_job_with_running_status(self, activity_environment, ateam, auser, anode, asaved_query):
        inputs = CreateDataModelingJobInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id="test-dag",
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
    async def test_marks_job_as_failed(self, activity_environment, ateam, anode, ajob):
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id="test-dag",
            job_id=str(ajob.id),
            error="Test error message",
        )
        await activity_environment.run(fail_materialization_activity, inputs)
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == DataModelingJob.Status.FAILED
        assert ajob.error == "Test error message"

    async def test_updates_node_system_properties(self, activity_environment, ateam, anode, ajob):
        inputs = FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id="test-dag",
            job_id=str(ajob.id),
            error="Query failed: timeout",
        )
        await activity_environment.run(fail_materialization_activity, inputs)
        await database_sync_to_async(anode.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props["last_run_status"] == "failed"
        assert system_props["last_run_job_id"] == str(ajob.id)
        assert system_props["last_run_error"] == "Query failed: timeout"
        assert "last_run_at" in system_props


class TestSucceedMaterializationActivity:
    async def test_marks_job_as_completed(self, activity_environment, ateam, anode, ajob):
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id="test-dag",
            job_id=str(ajob.id),
            row_count=1000,
            duration_seconds=45.5,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == DataModelingJob.Status.COMPLETED
        assert ajob.error is None
        assert ajob.last_run_at is not None

    async def test_updates_node_system_properties(self, activity_environment, ateam, anode, ajob):
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id="test-dag",
            job_id=str(ajob.id),
            row_count=500,
            duration_seconds=30.0,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)
        await database_sync_to_async(anode.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props["last_run_status"] == "completed"
        assert system_props["last_run_job_id"] == str(ajob.id)
        assert system_props["last_run_rows"] == 500
        assert system_props["last_run_duration_seconds"] == 30.0
        assert system_props.get("last_run_error") is None
        assert "last_run_at" in system_props

    async def test_clears_previous_error(self, activity_environment, ateam, anode, ajob):
        anode.properties = {"system": {"last_run_error": "Previous error"}}
        await database_sync_to_async(anode.save)()
        inputs = SucceedMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id="test-dag",
            job_id=str(ajob.id),
            row_count=100,
            duration_seconds=10.0,
        )
        await activity_environment.run(succeed_materialization_activity, inputs)
        await database_sync_to_async(anode.refresh_from_db)()
        system_props = anode.properties.get("system", {})
        assert system_props.get("last_run_error") is None


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
            mock_create_table.return_value = warehouse_table
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
            mock_create_table.return_value = warehouse_table
            await activity_environment.run(prepare_queryable_table_activity, inputs)
            await database_sync_to_async(asaved_query.refresh_from_db)()
            assert asaved_query.table_id == warehouse_table.id
            await database_sync_to_async(warehouse_table.refresh_from_db)()
            assert warehouse_table.row_count == 250
        await database_sync_to_async(warehouse_table.delete)()


class TestMaterializeViewActivity:
    async def test_rejects_table_node_type(self, activity_environment, ateam, ajob):
        table_node = await database_sync_to_async(Node.objects.create)(
            team=ateam,
            dag_id="test-dag",
            name="source_table",
            type=NodeType.TABLE,
        )
        inputs = MaterializeViewInputs(
            team_id=ateam.pk,
            dag_id="test-dag",
            node_id=str(table_node.id),
            job_id=str(ajob.id),
        )
        with pytest.raises(InvalidNodeTypeException, match="Cannot materialize a TABLE node"):
            await activity_environment.run(materialize_view_activity, inputs)
        await database_sync_to_async(table_node.delete)()

    async def test_materializes_view_to_delta_table(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name
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
                AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                AIRBYTE_BUCKET_REGION="us-east-1",
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
                dag_id="test-dag",
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
        self, activity_environment, ateam, anode, ajob, bucket_name
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
                AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                AIRBYTE_BUCKET_REGION="us-east-1",
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
                dag_id="test-dag",
                node_id=str(anode.id),
                job_id=str(ajob.id),
            )
            result = await activity_environment.run(materialize_view_activity, inputs)
            await database_sync_to_async(ajob.refresh_from_db)()
            assert ajob.rows_expected == 5
            assert ajob.rows_materialized == 5
            assert result.row_count == 5
