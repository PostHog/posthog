import uuid
from django.conf import settings
from dlt.common.schema.typing import TSchemaTables
from dlt.common.data_types.typing import TDataType
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)

from posthog.warehouse.models import (
    get_or_create_datawarehouse_credential,
    DataWarehouseTable,
    DataWarehouseCredential,
    get_external_data_job,
    asave_datawarehousetable,
    acreate_datawarehousetable,
    asave_external_data_schema,
    get_table_by_schema_id,
    aget_schema_by_id,
)

from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.temporal.common.logger import bind_temporal_worker_logger
from clickhouse_driver.errors import ServerException
from asgiref.sync import sync_to_async
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from dlt.common.normalizers.naming.snake_case import NamingConvention


def dlt_to_hogql_type(dlt_type: TDataType | None) -> str:
    hogql_type: type[DatabaseField] = DatabaseField

    if dlt_type is None:
        hogql_type = StringDatabaseField
    elif dlt_type == "text":
        hogql_type = StringDatabaseField
    elif dlt_type == "double":
        hogql_type = IntegerDatabaseField
    elif dlt_type == "bool":
        hogql_type = BooleanDatabaseField
    elif dlt_type == "timestamp":
        hogql_type = DateTimeDatabaseField
    elif dlt_type == "bigint":
        hogql_type = IntegerDatabaseField
    elif dlt_type == "binary":
        raise Exception("DLT type 'binary' is not a supported column type")
    elif dlt_type == "complex":
        hogql_type = StringJSONDatabaseField
    elif dlt_type == "decimal":
        hogql_type = IntegerDatabaseField
    elif dlt_type == "wei":
        raise Exception("DLT type 'wei' is not a supported column type")
    elif dlt_type == "date":
        hogql_type = DateDatabaseField
    elif dlt_type == "time":
        hogql_type = DateTimeDatabaseField
    else:
        raise Exception(f"DLT type '{dlt_type}' is not a supported column type")

    return hogql_type.__name__


async def validate_schema(
    credential: DataWarehouseCredential, table_name: str, new_url_pattern: str, team_id: int, row_count: int
) -> dict:
    params = {
        "credential": credential,
        "name": table_name,
        "format": "Parquet",
        "url_pattern": new_url_pattern,
        "team_id": team_id,
        "row_count": row_count,
    }

    table = DataWarehouseTable(**params)
    table.columns = await sync_to_async(table.get_columns)(safe_expose_ch_error=False)

    return {
        "credential": credential,
        "name": table_name,
        "format": "Parquet",
        "url_pattern": new_url_pattern,
        "team_id": team_id,
        "row_count": row_count,
    }


async def validate_schema_and_update_table(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    table_schema: TSchemaTables,
    row_count: int,
) -> None:
    """

    Validates the schemas of data that has been synced by external data job.
    If the schemas are valid, it creates or updates the DataWarehouseTable model with the new url pattern.

    Arguments:
        run_id: The id of the external data job
        team_id: The id of the team
        schema_id: The schema for which the data job relates to
        table_schema: The DLT schema from the data load stage
        table_row_counts: The count of synced rows from DLT
    """

    logger = await bind_temporal_worker_logger(team_id=team_id)

    job: ExternalDataJob = await get_external_data_job(job_id=run_id)

    credential: DataWarehouseCredential = await get_or_create_datawarehouse_credential(
        team_id=team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    external_data_schema: ExternalDataSchema = await aget_schema_by_id(schema_id, team_id)

    _schema_id = external_data_schema.id
    _schema_name: str = external_data_schema.name
    incremental = external_data_schema.is_incremental

    table_name = f"{job.pipeline.prefix or ''}{job.pipeline.source_type}_{_schema_name}".lower()
    normalized_schema_name = NamingConvention().normalize_identifier(_schema_name)
    new_url_pattern = job.url_pattern_by_schema(normalized_schema_name)

    # Check
    try:
        logger.info(f"Row count for {_schema_name} ({_schema_id}) are {row_count}")

        data = await validate_schema(
            credential=credential,
            table_name=table_name,
            new_url_pattern=new_url_pattern,
            team_id=team_id,
            row_count=row_count,
        )

        # create or update
        table_created: DataWarehouseTable | None = await get_table_by_schema_id(_schema_id, team_id)
        if table_created:
            table_created.credential = data.get("credential")
            table_created.url_pattern = new_url_pattern
            if incremental:
                table_created.row_count = await sync_to_async(table_created.get_count)()
            else:
                table_created.row_count = row_count
            await asave_datawarehousetable(table_created)

        if not table_created:
            table_created = await acreate_datawarehousetable(external_data_source_id=job.pipeline.id, **data)

        assert isinstance(table_created, DataWarehouseTable) and table_created is not None

        for schema in table_schema.values():
            if schema.get("resource") == _schema_name:
                schema_columns = schema.get("columns") or {}
                raw_db_columns: dict[str, dict[str, str]] = await sync_to_async(table_created.get_columns)()
                db_columns = {key: column.get("clickhouse", "") for key, column in raw_db_columns.items()}

                columns = {}
                for column_name, db_column_type in db_columns.items():
                    dlt_column = schema_columns.get(column_name)
                    if dlt_column is not None:
                        dlt_data_type = dlt_column.get("data_type")
                        hogql_type = dlt_to_hogql_type(dlt_data_type)
                    else:
                        hogql_type = dlt_to_hogql_type(None)

                    columns[column_name] = {
                        "clickhouse": db_column_type,
                        "hogql": hogql_type,
                    }
                table_created.columns = columns
                break

        await asave_datawarehousetable(table_created)

        # schema could have been deleted by this point
        schema_model = await aget_schema_by_id(schema_id=_schema_id, team_id=team_id)

        if schema_model:
            schema_model.table = table_created
            schema_model.last_synced_at = job.created_at
            await asave_external_data_schema(schema_model)

    except ServerException as err:
        if err.code == 636:
            logger.exception(
                f"Data Warehouse: No data for schema {_schema_name} for external data job {job.pk}",
                exc_info=err,
            )
        else:
            logger.exception(
                f"Data Warehouse: Unknown ServerException {job.pk}",
                exc_info=err,
            )
    except Exception as e:
        # TODO: handle other exceptions here
        logger.exception(
            f"Data Warehouse: Could not validate schema for external data job {job.pk}",
            exc_info=e,
        )
        raise e

    # TODO: figure out data deletes - currently borked right now
    # if (
    #     last_successful_job
    #     and _schema_name not in PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING[job.pipeline.source_type]
    # ):
    #     try:
    #         last_successful_job.delete_data_in_bucket()
    #     except Exception as e:
    #         logger.exception(
    #             f"Data Warehouse: Could not delete deprecated data source {last_successful_job.pk}",
    #             exc_info=e,
    #         )
