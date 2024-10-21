import dataclasses

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.temporal.data_imports.pipelines.schemas import PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING

from posthog.warehouse.models import sync_old_schemas_with_new_schemas, ExternalDataSource
from posthog.warehouse.models.external_data_schema import (
    get_sql_schemas_for_source_type,
    get_snowflake_schemas,
)
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


@dataclasses.dataclass
class SyncNewSchemasActivityInputs:
    source_id: str
    team_id: int


@activity.defn
async def sync_new_schemas_activity(inputs: SyncNewSchemasActivityInputs) -> None:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    logger.info("Syncing new -> old schemas")

    source = await sync_to_async(ExternalDataSource.objects.get)(team_id=inputs.team_id, id=inputs.source_id)

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

        sql_schemas = await sync_to_async(get_sql_schemas_for_source_type)(
            source.source_type, host, port, database, user, password, db_schema, ssh_tunnel
        )

        schemas_to_sync = list(sql_schemas.keys())
    elif source.source_type == ExternalDataSource.Type.SNOWFLAKE:
        if not source.job_inputs:
            return

        account_id = source.job_inputs.get("account_id")
        user = source.job_inputs.get("user")
        password = source.job_inputs.get("password")
        database = source.job_inputs.get("database")
        warehouse = source.job_inputs.get("warehouse")
        sf_schema = source.job_inputs.get("schema")
        role = source.job_inputs.get("role")

        sql_schemas = await sync_to_async(get_snowflake_schemas)(
            account_id, database, warehouse, user, password, sf_schema, role
        )

        schemas_to_sync = list(sql_schemas.keys())
    else:
        schemas_to_sync = list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING.get(source.source_type, ()))

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    schemas_created = await sync_to_async(sync_old_schemas_with_new_schemas)(
        schemas_to_sync,
        source_id=inputs.source_id,
        team_id=inputs.team_id,
    )

    if len(schemas_created) > 0:
        logger.info(f"Added new schemas: {', '.join(schemas_created)}")
    else:
        logger.info("No new schemas to create")
