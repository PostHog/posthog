from django.conf import settings

from posthog.warehouse.models import (
    get_latest_run_if_exists,
    get_or_create_datawarehouse_credential,
    get_table_by_url_pattern_and_source,
    DataWarehouseTable,
    DataWarehouseCredential,
    get_schema_if_exists,
)
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.temporal.common.logger import bind_temporal_worker_logger
from asgiref.sync import async_to_sync
from clickhouse_driver.errors import ServerException
from typing import Dict
from django.db import close_old_connections


def validate_schema(credential: DataWarehouseCredential, table_name: str, new_url_pattern: str, team_id: int) -> Dict:
    params = {
        "credential": credential,
        "name": table_name,
        "format": "Parquet",
        "url_pattern": new_url_pattern,
        "team_id": team_id,
    }

    table = DataWarehouseTable(**params)
    table.columns = table.get_columns(safe_expose_ch_error=False)

    return {
        "credential": credential,
        "name": table_name,
        "format": "Parquet",
        "url_pattern": new_url_pattern,
        "team_id": team_id,
    }


# TODO: make async
def validate_schema_and_update_table(run_id: str, team_id: int, schemas: list[str]) -> None:
    """

    Validates the schemas of data that has been synced by external data job.
    If the schemas are valid, it creates or updates the DataWarehouseTable model with the new url pattern.

    Arguments:
        run_id: The id of the external data job
        team_id: The id of the team
        schemas: The list of schemas that have been synced by the external data job
    """

    logger = async_to_sync(bind_temporal_worker_logger)(team_id=team_id)

    close_old_connections()
    job = ExternalDataJob.objects.get(pk=run_id)

    last_successful_job = get_latest_run_if_exists(job.team_id, job.pipeline_id)

    credential = get_or_create_datawarehouse_credential(
        team_id=job.team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    for _schema_name in schemas:
        table_name = f"{job.pipeline.prefix or ''}{job.pipeline.source_type}_{_schema_name}".lower()
        new_url_pattern = job.url_pattern_by_schema(_schema_name)

        # Check
        try:
            data = validate_schema(
                credential=credential, table_name=table_name, new_url_pattern=new_url_pattern, team_id=team_id
            )
        except ServerException as err:
            if err.code == 636:
                logger.exception(
                    f"Data Warehouse: No data for schema {_schema_name} for external data job {job.pk}",
                    exc_info=err,
                )
            continue
        except Exception as e:
            # TODO: handle other exceptions here
            logger.exception(
                f"Data Warehouse: Could not validate schema for external data job {job.pk}",
                exc_info=e,
            )
            continue

        # create or update
        table_created = None
        if last_successful_job:
            old_url_pattern = last_successful_job.url_pattern_by_schema(_schema_name)
            try:
                table_created = get_table_by_url_pattern_and_source(
                    team_id=job.team_id, source_id=job.pipeline.id, url_pattern=old_url_pattern
                )
            except Exception:
                table_created = None
            else:
                table_created.url_pattern = new_url_pattern
                table_created.save()

        if not table_created:
            table_created = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **data)

        table_created.columns = table_created.get_columns()
        table_created.save()

        # schema could have been deleted by this point
        schema_model = get_schema_if_exists(schema_name=_schema_name, team_id=job.team_id, source_id=job.pipeline.id)

        if schema_model:
            schema_model.table = table_created
            schema_model.last_synced_at = job.created_at
            schema_model.save()

    if last_successful_job:
        try:
            last_successful_job.delete_data_in_bucket()
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Could not delete deprecated data source {last_successful_job.pk}",
                exc_info=e,
            )
            pass
