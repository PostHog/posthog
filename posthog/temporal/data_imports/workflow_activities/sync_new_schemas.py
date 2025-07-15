import dataclasses
import typing as t

from django.db import close_old_connections
from temporalio import activity

from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.temporal.data_imports.pipelines.bigquery import BigQuerySourceConfig, get_schemas as get_bigquery_schemas
from posthog.temporal.data_imports.pipelines.doit.source import DoItSourceConfig, doit_list_reports
from posthog.temporal.data_imports.pipelines.google_sheets.source import (
    GoogleSheetsServiceAccountSourceConfig,
    get_schemas as get_google_sheets_schemas,
)
from posthog.temporal.data_imports.pipelines.mssql import MSSQLSourceConfig, get_schemas as get_mssql_schemas
from posthog.temporal.data_imports.pipelines.mysql import MySQLSourceConfig, get_schemas as get_mysql_schemas
from posthog.temporal.data_imports.pipelines.mongo import MongoSourceConfig, get_schemas as get_mongo_schemas
from posthog.temporal.data_imports.pipelines.postgres import PostgreSQLSourceConfig, get_schemas as get_postgres_schemas
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.temporal.data_imports.pipelines.snowflake import (
    SnowflakeSourceConfig,
    get_schemas as get_snowflake_schemas,
)
from posthog.warehouse.models import (
    ExternalDataSource,
    sync_old_schemas_with_new_schemas,
)


@dataclasses.dataclass
class SyncNewSchemasActivityInputs:
    source_id: str
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "source_id": self.source_id,
            "team_id": self.team_id,
        }


@activity.defn
def sync_new_schemas_activity(inputs: SyncNewSchemasActivityInputs) -> None:
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    close_old_connections()

    logger.info("Syncing new -> old schemas")

    source = ExternalDataSource.objects.get(team_id=inputs.team_id, id=inputs.source_id)

    schemas_to_sync: list[str] = []

    if source.source_type == ExternalDataSource.Type.POSTGRES:
        if not source.job_inputs:
            return

        schemas = get_postgres_schemas(PostgreSQLSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = list(schemas.keys())

    elif source.source_type == ExternalDataSource.Type.MYSQL:
        if not source.job_inputs:
            return

        schemas = get_mysql_schemas(MySQLSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = list(schemas.keys())

    elif source.source_type == ExternalDataSource.Type.MSSQL:
        if not source.job_inputs:
            return

        schemas = get_mssql_schemas(MSSQLSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = list(schemas.keys())

    elif source.source_type == ExternalDataSource.Type.SNOWFLAKE:
        if not source.job_inputs:
            return

        schemas = get_snowflake_schemas(SnowflakeSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = list(schemas.keys())

    elif source.source_type == ExternalDataSource.Type.BIGQUERY:
        if not source.job_inputs:
            return

        schemas = get_bigquery_schemas(BigQuerySourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = list(schemas.keys())
    elif source.source_type == ExternalDataSource.Type.DOIT:
        if not source.job_inputs:
            return

        doit_schemas = doit_list_reports(DoItSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = [name for name, _ in doit_schemas]
    elif source.source_type == ExternalDataSource.Type.GOOGLESHEETS:
        if not source.job_inputs:
            return

        sheets_schemas = get_google_sheets_schemas(GoogleSheetsServiceAccountSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = [name for name, _ in sheets_schemas]
    elif source.source_type == ExternalDataSource.Type.MONGODB:
        if not source.job_inputs:
            return

        schemas = get_mongo_schemas(MongoSourceConfig.from_dict(source.job_inputs))
        schemas_to_sync = list(schemas.keys())
    else:
        schemas_to_sync = list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING.get(source.source_type, ()))

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    schemas_created = sync_old_schemas_with_new_schemas(
        schemas_to_sync,
        source_id=inputs.source_id,
        team_id=inputs.team_id,
    )

    if len(schemas_created) > 0:
        logger.info(f"Added new schemas: {', '.join(schemas_created)}")
    else:
        logger.info("No new schemas to create")
