import asyncio
import threading
from collections.abc import Callable

import pytest
from unittest.mock import AsyncMock, patch

from posthog.models import Team

from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery
from products.data_modeling.backend.facade.tasks import refresh_downstream_view_columns
from products.data_warehouse.backend.logic.data_load.create_table import create_table_from_saved_query
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("name", ["concurrent_model", "models.concurrent_model"])
async def test_concurrent_materializations_share_one_backing_table(team: Team, name: str) -> None:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name=name,
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
@pytest.mark.parametrize("name", ["snapshot_model", "models.snapshot_model"])
async def test_materialization_replaces_table_metadata_in_one_snapshot(team: Team, name: str) -> None:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name=name,
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
    )
    baseline_columns = {"baseline": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}}
    # bulk_create skips save() validation, like a backing table written before created_via existed.
    [table] = await DataWarehouseTable.objects.abulk_create(
        [
            DataWarehouseTable(
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
        ]
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
        patch.object(refresh_downstream_view_columns, "delay") as refresh_delay,
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
    assert table.created_via == DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW
    refresh_delay.assert_called_once_with(team.pk, str(saved_query.id), None)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_given_row_count_and_size_are_recorded_without_reading_the_files(team: Team) -> None:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name="counted_model",
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
    )
    job = await DataModelingJob.objects.acreate(
        team=team,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id="counted-workflow",
    )

    with (
        patch.object(DataWarehouseTable, "get_columns", return_value={}),
        patch.object(DataWarehouseTable, "get_count", side_effect=RuntimeError("the files must not be counted")),
        patch(
            "products.data_warehouse.backend.logic.data_load.create_table.calculate_table_size",
            new_callable=AsyncMock,
            return_value=99.0,
        ),
    ):
        result = await create_table_from_saved_query(
            str(job.id), str(saved_query.id), team.pk, "folder", row_count=42, size_in_s3_mib=3.0
        )

    await result.table.arefresh_from_db()
    assert (result.table.row_count, result.table.size_in_s3_mib) == (42, 3.0)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_concurrent_publishes_run_their_blocking_reads_at_the_same_time(team: Team) -> None:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name="parallel_model",
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
    )
    first_job, second_job = [
        await DataModelingJob.objects.acreate(
            team=team,
            saved_query=saved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id=workflow_id,
        )
        for workflow_id in ("first-workflow", "second-workflow")
    ]
    both_publishes_reading = threading.Barrier(2, timeout=5)

    def read_alongside_the_other_publish(result: object) -> Callable[..., object]:
        def read(*args: object, **kwargs: object) -> object:
            both_publishes_reading.wait()
            return result

        return read

    with (
        patch.object(DataWarehouseTable, "get_columns", side_effect=read_alongside_the_other_publish({})),
        patch.object(DataWarehouseTable, "get_count", side_effect=read_alongside_the_other_publish(1)),
        patch(
            "products.data_warehouse.backend.logic.data_load.create_table.get_size_of_folder",
            side_effect=read_alongside_the_other_publish(3.0),
        ),
    ):
        first_result, second_result = await asyncio.gather(
            create_table_from_saved_query(str(first_job.id), str(saved_query.id), team.pk, "first-folder"),
            create_table_from_saved_query(str(second_job.id), str(saved_query.id), team.pk, "second-folder"),
        )

    assert [(result.table.row_count, result.total_storage_mib) for result in (first_result, second_result)] == [
        (1, 3.0),
        (1, 3.0),
    ]


async def _materialized_table_with_size(team: Team, name: str, queryable_folder: str) -> DataWarehouseSavedQuery:
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=team,
        name=name,
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
    )
    [table] = await DataWarehouseTable.objects.abulk_create(
        [
            DataWarehouseTable(
                team=team,
                name=saved_query.name,
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                url_pattern=saved_query.url_pattern,
                queryable_folder=queryable_folder,
                created_via=DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW,
                row_count=10,
                size_in_s3_mib=10.0,
            )
        ]
    )
    saved_query.table = table
    await saved_query.asave(update_fields=["table", "updated_at"])
    return saved_query


async def _running_job(team: Team, saved_query: DataWarehouseSavedQuery, workflow_id: str) -> DataModelingJob:
    return await DataModelingJob.objects.acreate(
        team=team,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id=workflow_id,
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_concurrent_publishes_count_the_storage_growth_once(team: Team) -> None:
    saved_query = await _materialized_table_with_size(team, "growing_model", "baseline-folder")
    first_job = await _running_job(team, saved_query, "first-workflow")
    second_job = await _running_job(team, saved_query, "second-workflow")
    both_publishes_listing = threading.Barrier(2, timeout=5)

    def list_alongside_the_other_publish(*args: object) -> float:
        both_publishes_listing.wait()
        return 25.0

    with (
        patch.object(DataWarehouseTable, "get_columns", return_value={}),
        patch(
            "products.data_warehouse.backend.logic.data_load.create_table.get_size_of_folder",
            side_effect=list_alongside_the_other_publish,
        ),
    ):
        results = await asyncio.gather(
            create_table_from_saved_query(str(first_job.id), str(saved_query.id), team.pk, "first-folder", row_count=1),
            create_table_from_saved_query(
                str(second_job.id), str(saved_query.id), team.pk, "second-folder", row_count=1
            ),
        )

    assert sum(result.storage_delta_mib or 0 for result in results) == 15.0


OWN_STAGED_FOLDER = "staged_model__query_1700000000_bbbbbbbb"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "published_folder,expected_published,expected_folder,expected_row_count",
    [
        ("staged_model__query_1800000000_aaaaaaaa", False, "staged_model__query_1800000000_aaaaaaaa", 10),
        ("staged_model__query_1600000000_aaaaaaaa", True, OWN_STAGED_FOLDER, 20),
    ],
)
async def test_a_publish_keeps_a_folder_staged_after_its_own(
    team: Team, published_folder: str, expected_published: bool, expected_folder: str, expected_row_count: int
) -> None:
    saved_query = await _materialized_table_with_size(team, "staged_model", published_folder)
    job = await _running_job(team, saved_query, "late-workflow")

    with (
        patch.object(DataWarehouseTable, "get_columns", return_value={}),
        patch(
            "products.data_warehouse.backend.logic.data_load.create_table.calculate_table_size",
            new_callable=AsyncMock,
            return_value=20.0,
        ),
    ):
        result = await create_table_from_saved_query(
            str(job.id), str(saved_query.id), team.pk, OWN_STAGED_FOLDER, row_count=20
        )

    table = saved_query.table
    assert table is not None
    await table.arefresh_from_db()
    assert (result.published, table.queryable_folder, table.row_count) == (
        expected_published,
        expected_folder,
        expected_row_count,
    )
