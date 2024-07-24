import dataclasses
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity

# TODO: remove dependency
from posthog.temporal.data_imports.pipelines.schemas import PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING

from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
)
from posthog.warehouse.models import sync_old_schemas_with_new_schemas, ExternalDataSource, aget_schema_by_id
from posthog.warehouse.models.external_data_schema import (
    ExternalDataSchema,
    get_sql_schemas_for_source_type,
    get_snowflake_schemas,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


@dataclasses.dataclass
class CreateExternalDataJobModelActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID


@activity.defn
async def create_external_data_job_model_activity(inputs: CreateExternalDataJobModelActivityInputs) -> tuple[str, bool]:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    try:
        run = await sync_to_async(create_external_data_job)(
            team_id=inputs.team_id,
            external_data_source_id=inputs.source_id,
            external_data_schema_id=inputs.schema_id,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
        )

        schema = await sync_to_async(ExternalDataSchema.objects.get)(team_id=inputs.team_id, id=inputs.schema_id)
        schema.status = ExternalDataSchema.Status.RUNNING
        await sync_to_async(schema.save)()

        source = await sync_to_async(ExternalDataSource.objects.get)(team_id=inputs.team_id, id=inputs.source_id)

        if source.source_type in [ExternalDataSource.Type.POSTGRES, ExternalDataSource.Type.MYSQL]:
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

            schemas_to_sync = await sync_to_async(get_sql_schemas_for_source_type)(
                source.source_type, host, port, database, user, password, db_schema, ssh_tunnel
            )
        elif source.source_type == ExternalDataSource.Type.SNOWFLAKE:
            account_id = source.job_inputs.get("account_id")
            user = source.job_inputs.get("user")
            password = source.job_inputs.get("password")
            database = source.job_inputs.get("database")
            warehouse = source.job_inputs.get("warehouse")
            sf_schema = source.job_inputs.get("schema")
            role = source.job_inputs.get("role")

            schemas_to_sync = await sync_to_async(get_snowflake_schemas)(
                account_id, database, warehouse, user, password, sf_schema, role
            )
        else:
            schemas_to_sync = list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING.get(source.source_type, ()))

        # TODO: this could cause a race condition where each schema worker creates the missing schema

        await sync_to_async(sync_old_schemas_with_new_schemas)(
            schemas_to_sync,
            source_id=inputs.source_id,
            team_id=inputs.team_id,
        )

        logger.info(
            f"Created external data job for external data source {inputs.source_id}",
        )

        schema_model = await aget_schema_by_id(inputs.schema_id, inputs.team_id)
        if schema_model is None:
            raise ValueError(f"Schema with ID {inputs.schema_id} not found")

        return str(run.id), schema_model.is_incremental
    except Exception as e:
        logger.exception(
            f"External data job failed on create_external_data_job_model_activity for {str(inputs.source_id)} with error: {e}"
        )
        raise
