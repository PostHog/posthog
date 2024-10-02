import dataclasses
from typing import Any
import uuid

from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.data_imports.pipelines.helpers import aremove_reset_pipeline, aupdate_job_count

from posthog.temporal.data_imports.pipelines.pipeline import DataImportPipeline, PipelineInputs
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSource,
    get_external_data_job,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger
from structlog.typing import FilteringBoundLogger
from posthog.warehouse.models.external_data_schema import ExternalDataSchema, aget_schema_by_id
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


@dataclasses.dataclass
class ImportDataActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str


@activity.defn
async def import_data_activity(inputs: ImportDataActivityInputs):
    async with Heartbeater(factor=30):  # Every 10 secs
        model: ExternalDataJob = await get_external_data_job(
            job_id=inputs.run_id,
        )

        logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

        job_inputs = PipelineInputs(
            source_id=inputs.source_id,
            schema_id=inputs.schema_id,
            run_id=inputs.run_id,
            team_id=inputs.team_id,
            job_type=model.pipeline.source_type,
            dataset_name=model.folder_path(),
        )

        reset_pipeline = model.pipeline.job_inputs.get("reset_pipeline", "False") == "True"

        schema: ExternalDataSchema = await aget_schema_by_id(inputs.schema_id, inputs.team_id)

        endpoints = [schema.name]

        source = None
        if model.pipeline.source_type == ExternalDataSource.Type.STRIPE:
            from posthog.temporal.data_imports.pipelines.stripe import stripe_source

            stripe_secret_key = model.pipeline.job_inputs.get("stripe_secret_key", None)
            account_id = model.pipeline.job_inputs.get("stripe_account_id", None)
            if not stripe_secret_key:
                raise ValueError(f"Stripe secret key not found for job {model.id}")

            source = stripe_source(
                api_key=stripe_secret_key,
                account_id=account_id,
                endpoint=schema.name,
                team_id=inputs.team_id,
                job_id=inputs.run_id,
                is_incremental=schema.is_incremental,
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.HUBSPOT:
            from posthog.temporal.data_imports.pipelines.hubspot.auth import hubspot_refresh_access_token
            from posthog.temporal.data_imports.pipelines.hubspot import hubspot

            hubspot_access_code = model.pipeline.job_inputs.get("hubspot_secret_key", None)
            refresh_token = model.pipeline.job_inputs.get("hubspot_refresh_token", None)
            if not refresh_token:
                raise ValueError(f"Hubspot refresh token not found for job {model.id}")

            if not hubspot_access_code:
                hubspot_access_code = hubspot_refresh_access_token(refresh_token)

            source = hubspot(
                api_key=hubspot_access_code,
                refresh_token=refresh_token,
                endpoints=tuple(endpoints),
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
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
                        source_type=model.pipeline.source_type,
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

                    return await _run(
                        job_inputs=job_inputs,
                        source=source,
                        logger=logger,
                        inputs=inputs,
                        schema=schema,
                        reset_pipeline=reset_pipeline,
                    )

            source = sql_source_for_type(
                source_type=model.pipeline.source_type,
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

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.SNOWFLAKE:
            from posthog.temporal.data_imports.pipelines.sql_database import snowflake_source

            account_id = model.pipeline.job_inputs.get("account_id")
            user = model.pipeline.job_inputs.get("user")
            password = model.pipeline.job_inputs.get("password")
            database = model.pipeline.job_inputs.get("database")
            warehouse = model.pipeline.job_inputs.get("warehouse")
            sf_schema = model.pipeline.job_inputs.get("schema")
            role = model.pipeline.job_inputs.get("role")

            source = snowflake_source(
                account_id=account_id,
                user=user,
                password=password,
                database=database,
                schema=sf_schema,
                warehouse=warehouse,
                role=role,
                table_names=endpoints,
                incremental_field=schema.sync_type_config.get("incremental_field") if schema.is_incremental else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.is_incremental
                else None,
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.SALESFORCE:
            from posthog.temporal.data_imports.pipelines.salesforce.auth import salesforce_refresh_access_token
            from posthog.temporal.data_imports.pipelines.salesforce import salesforce_source
            from posthog.models.integration import aget_integration_by_id

            salesforce_integration_id = model.pipeline.job_inputs.get("salesforce_integration_id", None)

            if not salesforce_integration_id:
                raise ValueError(f"Salesforce integration not found for job {model.id}")

            integration = await aget_integration_by_id(integration_id=salesforce_integration_id, team_id=inputs.team_id)
            salesforce_refresh_token = integration.refresh_token

            if not salesforce_refresh_token:
                raise ValueError(f"Salesforce refresh token not found for job {model.id}")

            salesforce_access_token = integration.access_token

            if not salesforce_access_token:
                salesforce_access_token = salesforce_refresh_access_token(salesforce_refresh_token)

            salesforce_instance_url = integration.config.get("instance_url")

            source = salesforce_source(
                instance_url=salesforce_instance_url,
                access_token=salesforce_access_token,
                refresh_token=salesforce_refresh_token,
                endpoint=schema.name,
                team_id=inputs.team_id,
                job_id=inputs.run_id,
                is_incremental=schema.is_incremental,
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )

        elif model.pipeline.source_type == ExternalDataSource.Type.ZENDESK:
            from posthog.temporal.data_imports.pipelines.zendesk import zendesk_source

            source = zendesk_source(
                subdomain=model.pipeline.job_inputs.get("zendesk_subdomain"),
                api_key=model.pipeline.job_inputs.get("zendesk_api_key"),
                email_address=model.pipeline.job_inputs.get("zendesk_email_address"),
                endpoint=schema.name,
                team_id=inputs.team_id,
                job_id=inputs.run_id,
                is_incremental=schema.is_incremental,
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.VITALLY:
            from posthog.temporal.data_imports.pipelines.vitally import vitally_source

            source = vitally_source(
                secret_token=model.pipeline.job_inputs.get("secret_token"),
                region=model.pipeline.job_inputs.get("region"),
                subdomain=model.pipeline.job_inputs.get("subdomain"),
                endpoint=schema.name,
                team_id=inputs.team_id,
                job_id=inputs.run_id,
                is_incremental=schema.is_incremental,
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.BIGQUERY:
            # from posthog.temporal.data_imports.pipelines.bigquery import bigquery_source
            from posthog.temporal.data_imports.pipelines.sql_database import bigquery_source

            dataset_id = model.pipeline.job_inputs.get("dataset_id")
            project_id = model.pipeline.job_inputs.get("project_id")
            private_key = model.pipeline.job_inputs.get("private_key")
            private_key_id = model.pipeline.job_inputs.get("private_key_id")
            client_email = model.pipeline.job_inputs.get("client_email")
            token_uri = model.pipeline.job_inputs.get("token_uri")

            source = bigquery_source(
                dataset_id=dataset_id,
                project_id=project_id,
                private_key=private_key,
                private_key_id=private_key_id,
                client_email=client_email,
                token_uri=token_uri,
                table_name=schema.name,
                incremental_field=schema.sync_type_config.get("incremental_field") if schema.is_incremental else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.is_incremental
                else None,
            )

            return await _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        else:
            raise ValueError(f"Source type {model.pipeline.source_type} not supported")


async def _run(
    job_inputs: PipelineInputs,
    source: Any,
    logger: FilteringBoundLogger,
    inputs: ImportDataActivityInputs,
    schema: ExternalDataSchema,
    reset_pipeline: bool,
):
    table_row_counts = await DataImportPipeline(job_inputs, source, logger, reset_pipeline, schema.is_incremental).run()
    total_rows_synced = sum(table_row_counts.values())

    await aupdate_job_count(inputs.run_id, inputs.team_id, total_rows_synced)
    await aremove_reset_pipeline(inputs.source_id)
