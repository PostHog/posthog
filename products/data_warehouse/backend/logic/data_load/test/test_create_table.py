import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from posthog.models import Team

from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery
from products.data_warehouse.backend.logic.data_load.create_table import create_table_from_saved_query
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_concurrent_materializations_share_one_backing_table(team: Team) -> None:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name="concurrent_model",
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
    )
    first_job, second_job = await asyncio.gather(
        DataModelingJob.objects.acreate(
            team=team,
            saved_query=saved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="first-workflow",
        ),
        DataModelingJob.objects.acreate(
            team=team,
            saved_query=saved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="second-workflow",
        ),
    )

    with (
        patch.object(DataWarehouseTable, "get_columns", return_value={}),
        patch.object(DataWarehouseTable, "get_count", return_value=1),
        patch(
            "products.data_warehouse.backend.logic.data_load.create_table.calculate_table_size",
            new_callable=AsyncMock,
            return_value=0.0,
        ),
    ):
        first_result, second_result = await asyncio.gather(
            create_table_from_saved_query(str(first_job.id), str(saved_query.id), team.pk, "first-folder"),
            create_table_from_saved_query(str(second_job.id), str(saved_query.id), team.pk, "second-folder"),
        )

    await saved_query.arefresh_from_db()
    table_count = await DataWarehouseTable.objects.filter(team=team, name=saved_query.name, deleted=False).acount()

    assert first_result.table.id == second_result.table.id
    assert saved_query.table_id == first_result.table.id
    assert table_count == 1
    assert first_result.table.created_via == DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_materialization_replaces_table_metadata_in_one_snapshot(team: Team) -> None:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name="snapshot_model",
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
    )
    baseline_columns = {"baseline": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}}
    table = await DataWarehouseTable.objects.acreate(
        team=team,
        name=saved_query.name,
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern=saved_query.url_pattern,
        queryable_folder="baseline-folder",
        columns=baseline_columns,
        column_order=["baseline"],
        row_count=10,
        size_in_s3_mib=10.0,
    )
    saved_query.table = table
    await saved_query.asave(update_fields=["table", "updated_at"])
    job = await DataModelingJob.objects.acreate(
        team=team,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id="replacement-workflow",
    )

    observed_snapshot: dict[str, object] = {}
    replacement_columns: dict[str, dict[str, str | bool]] = {
        "replacement": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}
    }

    def get_columns(table_being_materialized: DataWarehouseTable) -> dict[str, dict[str, str | bool]]:
        persisted_table = DataWarehouseTable.objects.get(id=table_being_materialized.id, team=team)
        observed_snapshot.update(
            queryable_folder=persisted_table.queryable_folder,
            columns=persisted_table.columns,
            column_order=persisted_table.column_order,
            row_count=persisted_table.row_count,
            size_in_s3_mib=persisted_table.size_in_s3_mib,
        )
        return replacement_columns

    with (
        patch.object(DataWarehouseTable, "get_columns", autospec=True, side_effect=get_columns),
        patch.object(DataWarehouseTable, "get_count", return_value=20),
        patch(
            "products.data_warehouse.backend.logic.data_load.create_table.calculate_table_size",
            new_callable=AsyncMock,
            return_value=20.0,
        ),
    ):
        await create_table_from_saved_query(str(job.id), str(saved_query.id), team.pk, "replacement-folder")

    assert observed_snapshot == {
        "queryable_folder": "baseline-folder",
        "columns": baseline_columns,
        "column_order": ["baseline"],
        "row_count": 10,
        "size_in_s3_mib": 10.0,
    }

    await table.arefresh_from_db()
    assert table.queryable_folder == "replacement-folder"
    assert table.columns == replacement_columns
    assert table.column_order == ["replacement"]
    assert table.row_count == 20
    assert table.size_in_s3_mib == 20.0
