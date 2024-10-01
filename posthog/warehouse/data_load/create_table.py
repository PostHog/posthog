import uuid

from django.conf import settings

from posthog.warehouse.models import (
    aget_or_create_datawarehouse_credential,
    DataWarehouseTable,
    DataWarehouseCredential,
    asave_datawarehousetable,
    acreate_datawarehousetable,
    aget_table_by_saved_query_id,
    aget_saved_query_by_id,
    asave_saved_query,
)

from asgiref.sync import sync_to_async
from posthog.temporal.common.logger import bind_temporal_worker_logger
from clickhouse_driver.errors import ServerException


async def create_table_from_saved_query(
    saved_query_id: str,
    team_id: int,
) -> None:
    """
    Create a table from a saved query if it doesn't exist.
    """
    logger = await bind_temporal_worker_logger(team_id=team_id)

    credential: DataWarehouseCredential = await aget_or_create_datawarehouse_credential(
        team_id=team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )
    saved_query_id_converted = str(uuid.UUID(saved_query_id))
    saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id_converted, team_id=team_id)

    try:
        table_name = f"mat_{saved_query.name}"
        url_pattern = saved_query.url_pattern
        table_format = DataWarehouseTable.TableFormat.Delta

        table_params = {
            "credential": credential,
            "name": table_name,
            "format": table_format,
            "url_pattern": url_pattern,
            "team_id": team_id,
        }

        # create or update
        table_created: DataWarehouseTable | None = await aget_table_by_saved_query_id(saved_query_id_converted, team_id)
        if table_created:
            table_created.credential = table_params.get("credential")
            table_created.format = table_params.get("format")
            table_created.url_pattern = url_pattern
            await asave_datawarehousetable(table_created)

        if not table_created:
            table_created = await acreate_datawarehousetable(**table_params)

        assert isinstance(table_created, DataWarehouseTable) and table_created is not None

        # TODO: handle dlt columns schemas. Need to refactor dag pipeline to pass through schema or propagate from upstream tables
        table_created.columns = await sync_to_async(table_created.get_columns)()
        await asave_datawarehousetable(table_created)

        saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id_converted, team_id=team_id)

        if saved_query:
            saved_query.table = table_created
            await asave_saved_query(saved_query)

    except ServerException as err:
        logger.exception(
            f"Data Warehouse: Unknown ServerException {saved_query.pk}",
            exc_info=err,
        )
    except Exception as e:
        # TODO: handle other exceptions here
        logger.exception(
            f"Data Warehouse: Could not validate schema for saved query materialization{saved_query.pk}",
            exc_info=e,
        )
        raise
