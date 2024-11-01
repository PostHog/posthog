from datetime import datetime
from typing import Any

from django.db.models import Prefetch, F

from temporalio import activity

from posthog.temporal.data_imports.pipelines.bigquery import delete_table

from posthog.temporal.data_imports.pipelines.pipeline import PipelineInputs
from posthog.temporal.data_imports.pipelines.pipeline_sync import DataImportPipelineSync
from posthog.temporal.data_imports.util import is_posthog_team
from posthog.temporal.data_imports.workflow_activities.import_data import ImportDataActivityInputs
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSource,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from structlog.typing import FilteringBoundLogger
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


@activity.defn
def import_data_activity_sync(inputs: ImportDataActivityInputs):
    model = ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(id=inputs.run_id)

    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)

    logger.info("Running *SYNC* import_data")

    job_inputs = PipelineInputs(
        source_id=inputs.source_id,
        schema_id=inputs.schema_id,
        run_id=inputs.run_id,
        team_id=inputs.team_id,
        job_type=ExternalDataSource.Type(model.pipeline.source_type),
        dataset_name=model.folder_path(),
    )

    reset_pipeline = model.pipeline.job_inputs.get("reset_pipeline", "False") == "True"

    schema = (
        ExternalDataSchema.objects.prefetch_related("source")
        .exclude(deleted=True)
        .get(id=inputs.schema_id, team_id=inputs.team_id)
    )

    endpoints = [schema.name]

    source = None
    if model.pipeline.source_type in [
        ExternalDataSource.Type.POSTGRES,
        ExternalDataSource.Type.MYSQL,
        ExternalDataSource.Type.MSSQL,
    ]:
        if is_posthog_team(inputs.team_id):
            from posthog.temporal.data_imports.pipelines.sql_database_v2 import sql_source_for_type
        else:
            from posthog.temporal.data_imports.pipelines.sql_database import sql_source_for_type

        host = model.pipeline.job_inputs.get("host")
        port = model.pipeline.job_inputs.get("port")
        user = model.pipeline.job_inputs.get("user")
        password = model.pipeline.job_inputs.get("password")
        database = model.pipeline.job_inputs.get("database")
        pg_schema = model.pipeline.job_inputs.get("schema")

        using_ssh_tunnel = str(model.pipeline.job_inputs.get("ssh_tunnel_enabled", False)) == "True"
        ssh_tunnel_host = model.pipeline.job_inputs.get("ssh_tunnel_host")
        ssh_tunnel_port = model.pipeline.job_inputs.get("ssh_tunnel_port")
        ssh_tunnel_auth_type = model.pipeline.job_inputs.get("ssh_tunnel_auth_type")
        ssh_tunnel_auth_type_username = model.pipeline.job_inputs.get("ssh_tunnel_auth_type_username")
        ssh_tunnel_auth_type_password = model.pipeline.job_inputs.get("ssh_tunnel_auth_type_password")
        ssh_tunnel_auth_type_passphrase = model.pipeline.job_inputs.get("ssh_tunnel_auth_type_passphrase")
        ssh_tunnel_auth_type_private_key = model.pipeline.job_inputs.get("ssh_tunnel_auth_type_private_key")

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

        if ssh_tunnel.enabled:
            with ssh_tunnel.get_tunnel(host, int(port)) as tunnel:
                if tunnel is None:
                    raise Exception("Can't open tunnel to SSH server")

                source = sql_source_for_type(
                    source_type=ExternalDataSource.Type(model.pipeline.source_type),
                    host=tunnel.local_bind_host,
                    port=tunnel.local_bind_port,
                    user=user,
                    password=password,
                    database=database,
                    sslmode="prefer",
                    schema=pg_schema,
                    table_names=endpoints,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.is_incremental
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.is_incremental
                    else None,
                    team_id=inputs.team_id,
                )

                return _run(
                    job_inputs=job_inputs,
                    source=source,
                    logger=logger,
                    inputs=inputs,
                    schema=schema,
                    reset_pipeline=reset_pipeline,
                )

        source = sql_source_for_type(
            source_type=ExternalDataSource.Type(model.pipeline.source_type),
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            sslmode="prefer",
            schema=pg_schema,
            table_names=endpoints,
            incremental_field=schema.sync_type_config.get("incremental_field") if schema.is_incremental else None,
            incremental_field_type=schema.sync_type_config.get("incremental_field_type")
            if schema.is_incremental
            else None,
            team_id=inputs.team_id,
        )

        return _run(
            job_inputs=job_inputs,
            source=source,
            logger=logger,
            inputs=inputs,
            schema=schema,
            reset_pipeline=reset_pipeline,
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.BIGQUERY:
        from posthog.temporal.data_imports.pipelines.sql_database_v2 import bigquery_source

        dataset_id = model.pipeline.job_inputs.get("dataset_id")
        project_id = model.pipeline.job_inputs.get("project_id")
        private_key = model.pipeline.job_inputs.get("private_key")
        private_key_id = model.pipeline.job_inputs.get("private_key_id")
        client_email = model.pipeline.job_inputs.get("client_email")
        token_uri = model.pipeline.job_inputs.get("token_uri")

        destination_table = f"{project_id}.{dataset_id}.__posthog_import_{inputs.run_id}_{str(datetime.now().timestamp()).replace('.', '')}"
        try:
            source = bigquery_source(
                dataset_id=dataset_id,
                project_id=project_id,
                private_key=private_key,
                private_key_id=private_key_id,
                client_email=client_email,
                token_uri=token_uri,
                table_name=schema.name,
                bq_destination_table_id=destination_table,
                incremental_field=schema.sync_type_config.get("incremental_field") if schema.is_incremental else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.is_incremental
                else None,
            )

            _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        except:
            raise
        finally:
            # Delete the destination table (if it exists) after we're done with it
            delete_table(
                table_id=destination_table,
                project_id=project_id,
                private_key=private_key,
                private_key_id=private_key_id,
                client_email=client_email,
                token_uri=token_uri,
            )
            logger.info(f"Deleting bigquery temp destination table: {destination_table}")
    else:
        raise ValueError(f"Source type {model.pipeline.source_type} not supported")


def _run(
    job_inputs: PipelineInputs,
    source: Any,
    logger: FilteringBoundLogger,
    inputs: ImportDataActivityInputs,
    schema: ExternalDataSchema,
    reset_pipeline: bool,
):
    table_row_counts = DataImportPipelineSync(job_inputs, source, logger, reset_pipeline, schema.is_incremental).run()
    total_rows_synced = sum(table_row_counts.values())

    ExternalDataJob.objects.filter(id=inputs.run_id, team_id=inputs.team_id).update(
        rows_synced=F("rows_synced") + total_rows_synced
    )
    source = ExternalDataSource.objects.get(id=inputs.source_id)
    source.job_inputs.pop("reset_pipeline", None)
    source.save()
