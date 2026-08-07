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
