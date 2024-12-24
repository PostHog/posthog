import dataclasses
import uuid
from datetime import datetime
from dateutil import parser
from typing import Any

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Prefetch, F

from temporalio import activity

from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE_V2
from posthog.models.integration import Integration
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.data_imports.pipelines.bigquery import delete_all_temp_destination_tables, delete_table

from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.pipelines.pipeline_sync import DataImportPipelineSync, PipelineInputs
from posthog.temporal.data_imports.util import is_posthog_team, is_enabled_for_team
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSource,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from structlog.typing import FilteringBoundLogger
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.types import IncrementalFieldType


@dataclasses.dataclass
class ImportDataActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str


def process_incremental_last_value(value: Any | None, field_type: IncrementalFieldType | None) -> Any | None:
    if value is None or field_type is None:
        return None

    if field_type == IncrementalFieldType.Integer or field_type == IncrementalFieldType.Numeric:
        return value

    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return parser.parse(value)

    if field_type == IncrementalFieldType.Date:
        return parser.parse(value).date()


@activity.defn
def import_data_activity_sync(inputs: ImportDataActivityInputs):
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)

    with HeartbeaterSync(factor=30, logger=logger):
        close_old_connections()

        model = ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        ).get(id=inputs.run_id)

        logger.debug("Running *SYNC* import_data")

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

        if settings.TEMPORAL_TASK_QUEUE == DATA_WAREHOUSE_TASK_QUEUE_V2:
            # Get the V2 last value, if it's not set yet (e.g. the first run), then fallback to the V1 value
            processed_incremental_last_value = process_incremental_last_value(
                schema.sync_type_config.get("incremental_field_last_value_v2"),
                schema.sync_type_config.get("incremental_field_type"),
            )

            if processed_incremental_last_value is None:
                processed_incremental_last_value = process_incremental_last_value(
                    schema.sync_type_config.get("incremental_field_last_value"),
                    schema.sync_type_config.get("incremental_field_type"),
                )
        else:
            processed_incremental_last_value = process_incremental_last_value(
                schema.sync_type_config.get("incremental_field_last_value"),
                schema.sync_type_config.get("incremental_field_type"),
            )

        if schema.is_incremental:
            logger.debug(f"Incremental last value being used is: {processed_incremental_last_value}")

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
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
            )

            return _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.HUBSPOT:
            from posthog.temporal.data_imports.pipelines.hubspot import hubspot
            from posthog.temporal.data_imports.pipelines.hubspot.auth import (
                hubspot_refresh_access_token,
            )

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

            return _run(
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
            if is_posthog_team(inputs.team_id) or is_enabled_for_team(inputs.team_id):
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

            using_ssl = str(model.pipeline.job_inputs.get("using_ssl", True)) == "True"

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
                        db_incremental_field_last_value=processed_incremental_last_value
                        if schema.is_incremental
                        else None,
                        team_id=inputs.team_id,
                        using_ssl=using_ssl,
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
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
                team_id=inputs.team_id,
                using_ssl=using_ssl,
            )

            return _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.SNOWFLAKE:
            if is_posthog_team(inputs.team_id):
                from posthog.temporal.data_imports.pipelines.sql_database_v2 import (
                    snowflake_source,
                )
            else:
                from posthog.temporal.data_imports.pipelines.sql_database import (
                    snowflake_source,
                )

            account_id = model.pipeline.job_inputs.get("account_id")
            database = model.pipeline.job_inputs.get("database")
            warehouse = model.pipeline.job_inputs.get("warehouse")
            sf_schema = model.pipeline.job_inputs.get("schema")
            role = model.pipeline.job_inputs.get("role")

            auth_type = model.pipeline.job_inputs.get("auth_type", "password")
            auth_type_username = model.pipeline.job_inputs.get("user")
            auth_type_password = model.pipeline.job_inputs.get("password")
            auth_type_passphrase = model.pipeline.job_inputs.get("passphrase")
            auth_type_private_key = model.pipeline.job_inputs.get("private_key")

            source = snowflake_source(
                account_id=account_id,
                auth_type=auth_type,
                user=auth_type_username,
                password=auth_type_password,
                private_key=auth_type_private_key,
                passphrase=auth_type_passphrase,
                database=database,
                schema=sf_schema,
                warehouse=warehouse,
                role=role,
                table_names=endpoints,
                incremental_field=schema.sync_type_config.get("incremental_field") if schema.is_incremental else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.is_incremental
                else None,
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
            )

            return _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.SALESFORCE:
            from posthog.temporal.data_imports.pipelines.salesforce import (
                salesforce_source,
            )
            from posthog.temporal.data_imports.pipelines.salesforce.auth import (
                salesforce_refresh_access_token,
            )

            salesforce_integration_id = model.pipeline.job_inputs.get("salesforce_integration_id", None)

            if not salesforce_integration_id:
                raise ValueError(f"Salesforce integration not found for job {model.id}")

            integration = Integration.objects.get(id=salesforce_integration_id, team_id=inputs.team_id)
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
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
            )

            return _run(
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
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
            )

            return _run(
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
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
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

            temporary_dataset_id = model.pipeline.job_inputs.get("temporary_dataset_id")
            using_temporary_dataset = (
                model.pipeline.job_inputs.get("using_temporary_dataset", False) and temporary_dataset_id is not None
            )

            destination_table_prefix = "__posthog_import_"
            destination_table_dataset_id = temporary_dataset_id if using_temporary_dataset else dataset_id
            destination_table = f"{project_id}.{destination_table_dataset_id}.{destination_table_prefix}{inputs.run_id}_{str(datetime.now().timestamp()).replace('.', '')}"

            delete_all_temp_destination_tables(
                dataset_id=dataset_id,
                table_prefix=destination_table_prefix,
                project_id=project_id,
                private_key=private_key,
                private_key_id=private_key_id,
                client_email=client_email,
                token_uri=token_uri,
                logger=logger,
            )

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
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.is_incremental
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.is_incremental
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
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
        elif model.pipeline.source_type == ExternalDataSource.Type.CHARGEBEE:
            from posthog.temporal.data_imports.pipelines.chargebee import (
                chargebee_source,
            )

            source = chargebee_source(
                api_key=model.pipeline.job_inputs.get("api_key"),
                site_name=model.pipeline.job_inputs.get("site_name"),
                endpoint=schema.name,
                team_id=inputs.team_id,
                job_id=inputs.run_id,
                is_incremental=schema.is_incremental,
                db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
            )

            return _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                inputs=inputs,
                schema=schema,
                reset_pipeline=reset_pipeline,
            )
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
    if settings.TEMPORAL_TASK_QUEUE == DATA_WAREHOUSE_TASK_QUEUE_V2:
        PipelineNonDLT(source, logger, job_inputs.run_id, schema.is_incremental).run()
    else:
        table_row_counts = DataImportPipelineSync(
            job_inputs, source, logger, reset_pipeline, schema.is_incremental
        ).run()
        total_rows_synced = sum(table_row_counts.values())

        ExternalDataJob.objects.filter(id=inputs.run_id, team_id=inputs.team_id).update(
            rows_synced=F("rows_synced") + total_rows_synced
        )

    source = ExternalDataSource.objects.get(id=inputs.source_id)
    source.job_inputs.pop("reset_pipeline", None)
    source.save()
