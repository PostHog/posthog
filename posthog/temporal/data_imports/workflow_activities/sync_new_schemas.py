import dataclasses
import typing as t

from django.db import close_old_connections
from temporalio import activity

from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.temporal.data_imports.pipelines.bigquery import get_schemas as get_bigquery_schemas
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.warehouse.models import (
    ExternalDataSource,
    sync_old_schemas_with_new_schemas,
)
from posthog.warehouse.models.external_data_schema import (
    get_snowflake_schemas,
    get_sql_schemas_for_source_type,
)
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


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

    if source.source_type in [
        ExternalDataSource.Type.POSTGRES,
        ExternalDataSource.Type.MYSQL,
        ExternalDataSource.Type.MSSQL,
    ]:
        if not source.job_inputs:
            return

        host = source.job_inputs.get("host")
        port = source.job_inputs.get("port")
        user = source.job_inputs.get("user")
        password = source.job_inputs.get("password")
        database = source.job_inputs.get("database")
        db_schema = source.job_inputs.get("schema")

        using_ssh_tunnel = str(source.job_inputs.get("ssh_tunnel_enabled", False)) == "True"
        ssh_tunnel_host = source.job_inputs.get("ssh_tunnel_host")
        ssh_tunnel_port = source.job_inputs.get("ssh_tunnel_port")
        ssh_tunnel_auth_type = source.job_inputs.get("ssh_tunnel_auth_type")
        ssh_tunnel_auth_type_username = source.job_inputs.get("ssh_tunnel_auth_type_username")
        ssh_tunnel_auth_type_password = source.job_inputs.get("ssh_tunnel_auth_type_password")
        ssh_tunnel_auth_type_passphrase = source.job_inputs.get("ssh_tunnel_auth_type_passphrase")
        ssh_tunnel_auth_type_private_key = source.job_inputs.get("ssh_tunnel_auth_type_private_key")

        using_ssl = str(source.job_inputs.get("using_ssl", True)) == "True"

        ssh_tunnel = SSHTunnel(
            enabled=using_ssh_tunnel,
            host=ssh_tunnel_host,
            port=ssh_tunnel_port,
            auth_type=ssh_tunnel_auth_type,
            username=ssh_tunnel_auth_type_username,
            password=ssh_tunnel_auth_type_password,
            passphrase=ssh_tunnel_auth_type_passphrase,
            private_key=ssh_tunnel_auth_type_private_key,
        )

        sql_schemas = get_sql_schemas_for_source_type(
            ExternalDataSource.Type(source.source_type),
            host,
            port,
            database,
            user,
            password,
            db_schema,
            ssh_tunnel,
            using_ssl,
        )

        schemas_to_sync = list(sql_schemas.keys())
    elif source.source_type == ExternalDataSource.Type.SNOWFLAKE:
        if not source.job_inputs:
            return

        account_id = source.job_inputs.get("account_id")
        database = source.job_inputs.get("database")
        warehouse = source.job_inputs.get("warehouse")
        sf_schema = source.job_inputs.get("schema")
        role = source.job_inputs.get("role")

        auth_type = source.job_inputs.get("auth_type", "password")
        auth_type_username = source.job_inputs.get("user")
        auth_type_password = source.job_inputs.get("password")
        auth_type_passphrase = source.job_inputs.get("passphrase")
        auth_type_private_key = source.job_inputs.get("private_key")

        sql_schemas = get_snowflake_schemas(
            account_id=account_id,
            database=database,
            warehouse=warehouse,
            user=auth_type_username,
            password=auth_type_password,
            schema=sf_schema,
            role=role,
            auth_type=auth_type,
            passphrase=auth_type_passphrase,
            private_key=auth_type_private_key,
        )

        schemas_to_sync = list(sql_schemas.keys())
    elif source.source_type == ExternalDataSource.Type.BIGQUERY:
        if not source.job_inputs:
            return

        dataset_id = source.job_inputs.get("dataset_id")
        project_id = source.job_inputs.get("project_id")
        private_key = source.job_inputs.get("private_key")
        private_key_id = source.job_inputs.get("private_key_id")
        client_email = source.job_inputs.get("client_email")
        token_uri = source.job_inputs.get("token_uri")

        bq_schemas = get_bigquery_schemas(
            dataset_id=dataset_id,
            project_id=project_id,
            private_key=private_key,
            private_key_id=private_key_id,
            client_email=client_email,
            token_uri=token_uri,
            logger=logger,
        )

        schemas_to_sync = list(bq_schemas.keys())
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
