import uuid
import datetime as dt

import pytest
from unittest import mock

import temporalio.worker
import temporalio.exceptions
from temporalio import activity as temporal_activity
from temporalio.testing import WorkflowEnvironment

from posthog.ducklake.client import DuckLakeExportResult
from posthog.temporal.data_modeling.activities import (
    CreateDataModelingJobInputs,
    DuckgresShadowInputs,
    DuckgresShadowResult,
    MaterializeViewInputs,
    MaterializeViewResult,
    PrepareQueryableTableInputs,
    PrepareQueryableTableResult,
    SucceedMaterializationInputs,
)
from posthog.temporal.data_modeling.activities.materialize_view_duckgres import (
    DuckLakeExportInputs,
    export_ducklake_to_parquet_activity,
)
from posthog.temporal.data_modeling.workflows.materialize_view import (
    MaterializeViewWorkflow,
    MaterializeViewWorkflowInputs,
    MaterializeViewWorkflowResult,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestExportDuckLakeToParquetActivity:
    async def test_maps_successful_export_to_result(self, activity_environment):
        export_result = DuckLakeExportResult(
            schema_name="shadow_1_models",
            table_name="my_view",
            row_count=3,
            destination="s3://ducklake-dev/ch_export/team_1/my_view.parquet",
        )
        inputs = DuckLakeExportInputs(team_id=1, schema_name="shadow_1_models", table_name="my_view")

        with mock.patch("posthog.ducklake.client.export_ducklake_table_to_parquet", return_value=export_result):
            result = await activity_environment.run(export_ducklake_to_parquet_activity, inputs)

        assert result.error is None
        assert result.row_count == 3
        assert result.destination == "s3://ducklake-dev/ch_export/team_1/my_view.parquet"

    async def test_swallows_export_error_into_result(self, activity_environment):
        inputs = DuckLakeExportInputs(team_id=1, schema_name="shadow_1_models", table_name="my_view")

        with mock.patch(
            "posthog.ducklake.client.export_ducklake_table_to_parquet",
            side_effect=RuntimeError("duckgres unreachable"),
        ):
            result = await activity_environment.run(export_ducklake_to_parquet_activity, inputs)

        assert result.error == "duckgres unreachable"
        assert result.row_count == 0
        assert result.destination == ""


class TestMaterializeViewWorkflowExportResilience:
    """A failing ClickHouse export must never fail the materialization workflow."""

    async def test_workflow_succeeds_when_export_activity_raises(self):
        node_id = str(uuid.uuid4())

        @temporal_activity.defn(name="check_duckgres_shadow_enabled_activity")
        async def stub_shadow_enabled(_: int) -> bool:
            return True

        @temporal_activity.defn(name="check_duckgres_export_enabled_activity")
        async def stub_export_enabled(_: int) -> bool:
            return True

        @temporal_activity.defn(name="create_data_modeling_job_activity")
        async def stub_create_job(_: CreateDataModelingJobInputs) -> str:
            return "test-job-id"

        @temporal_activity.defn(name="materialize_view_activity")
        async def stub_materialize(_: MaterializeViewInputs) -> MaterializeViewResult:
            return MaterializeViewResult(
                node_id=node_id,
                node_name="my_view",
                row_count=42,
                table_uri="s3://bucket/model",
                file_uris=["s3://bucket/model/data.parquet"],
                saved_query_id="sq-1",
            )

        @temporal_activity.defn(name="prepare_queryable_table_activity")
        async def stub_prepare(_: PrepareQueryableTableInputs) -> PrepareQueryableTableResult:
            return PrepareQueryableTableResult(storage_delta_mib=1.0, total_storage_mib=2.0)

        @temporal_activity.defn(name="succeed_materialization_activity")
        async def stub_succeed(_: SucceedMaterializationInputs) -> None:
            return None

        @temporal_activity.defn(name="materialize_view_duckgres_activity")
        async def stub_shadow(_: DuckgresShadowInputs) -> DuckgresShadowResult:
            return DuckgresShadowResult(
                row_count=42,
                duration_seconds=1.0,
                schema_name="shadow_1_models",
                table_name="my_view",
            )

        @temporal_activity.defn(name="export_ducklake_to_parquet_activity")
        async def stub_export_raises(_: DuckLakeExportInputs) -> None:
            raise temporalio.exceptions.ApplicationError("forced export failure", non_retryable=True)

        # fail_materialization_activity is intentionally not registered: if the export failure
        # leaked into the workflow's failure path, the worker would error on the missing activity.
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-export-resilience",
                workflows=[MaterializeViewWorkflow],
                activities=[
                    stub_shadow_enabled,
                    stub_export_enabled,
                    stub_create_job,
                    stub_materialize,
                    stub_prepare,
                    stub_succeed,
                    stub_shadow,
                    stub_export_raises,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result: MaterializeViewWorkflowResult = await env.client.execute_workflow(
                    MaterializeViewWorkflow.run,
                    MaterializeViewWorkflowInputs(team_id=1, dag_id="test-dag", node_id=node_id),
                    id=f"test-export-resilience-{uuid.uuid4()}",
                    task_queue="test-export-resilience",
                    execution_timeout=dt.timedelta(seconds=30),
                )

        # The export raised, yet the materialization still completed successfully.
        assert result.node_id == node_id
        assert result.rows_materialized == 42
