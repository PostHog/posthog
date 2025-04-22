import dataclasses
import uuid
from datetime import datetime
from typing import Any, Optional

from dateutil import parser
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Prefetch
from dlt.sources import DltSource
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.models.integration import Integration
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.bigquery import (
    delete_all_temp_destination_tables,
    delete_table,
)
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.types import IncrementalFieldType


@dataclasses.dataclass
class ImportDataActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str
    reset_pipeline: Optional[bool] = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "run_id": self.run_id,
            "reset_pipeline": self.reset_pipeline,
        }


def process_incremental_last_value(value: Any | None, field_type: IncrementalFieldType | None) -> Any | None:
    if value is None or value == "None" or field_type is None:
        return None

    if field_type == IncrementalFieldType.Integer or field_type == IncrementalFieldType.Numeric:
        return value

    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return parser.parse(value)

    if field_type == IncrementalFieldType.Date:
        return parser.parse(value).date()


def _trim_source_job_inputs(source: ExternalDataSource) -> None:
    if not source.job_inputs:
        return

    did_update_inputs = False
    for key, value in source.job_inputs.items():
        if isinstance(value, str):
            if value.startswith(" ") or value.endswith(" "):
                source.job_inputs[key] = value.strip()
                did_update_inputs = True

    if did_update_inputs:
        source.save()


@activity.defn
def import_data_activity_sync(inputs: ImportDataActivityInputs):
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)

    with HeartbeaterSync(factor=30, logger=logger), ShutdownMonitor() as shutdown_monitor:
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

        _trim_source_job_inputs(model.pipeline)

        schema: ExternalDataSchema | None = model.schema
        assert schema is not None

        if inputs.reset_pipeline is not None:
            reset_pipeline = inputs.reset_pipeline
        else:
            reset_pipeline = schema.sync_type_config.get("reset_pipeline", False) is True

        logger.debug(f"schema.sync_type_config = {schema.sync_type_config}")
        logger.debug(f"reset_pipeline = {reset_pipeline}")

        schema = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=inputs.schema_id, team_id=inputs.team_id)
        )

        endpoints = [schema.name]
        processed_incremental_last_value = None

        if reset_pipeline is not True:
            processed_incremental_last_value = process_incremental_last_value(
                schema.sync_type_config.get("incremental_field_last_value"),
                schema.sync_type_config.get("incremental_field_type"),
            )

        if schema.is_incremental:
            logger.debug(f"Incremental last value being used is: {processed_incremental_last_value}")

        source: DltSource | SourceResponse

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
                shutdown_monitor=shutdown_monitor,
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
                shutdown_monitor=shutdown_monitor,
            )
        elif model.pipeline.source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
            from posthog.temporal.data_imports.pipelines.mssql.mssql import mssql_source
            from posthog.temporal.data_imports.pipelines.mysql.mysql import mysql_source
            from posthog.temporal.data_imports.pipelines.postgres.postgres import (
                postgres_source,
            )
            from posthog.temporal.data_imports.pipelines.sql_database import (
                sql_source_for_type,
            )

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

                    if ExternalDataSource.Type(model.pipeline.source_type) == ExternalDataSource.Type.POSTGRES:
                        source = postgres_source(
                            host=tunnel.local_bind_host,
                            port=tunnel.local_bind_port,
                            user=user,
                            password=password,
                            database=database,
                            sslmode="prefer",
                            schema=pg_schema,
                            table_names=endpoints,
                            is_incremental=schema.is_incremental,
                            logger=logger,
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
                        )
                    elif ExternalDataSource.Type(model.pipeline.source_type) == ExternalDataSource.Type.MYSQL:
                        source = mysql_source(
                            host=tunnel.local_bind_host,
                            port=int(tunnel.local_bind_port),
                            user=user,
                            password=password,
                            database=database,
                            using_ssl=using_ssl,
                            schema=pg_schema,
                            table_names=endpoints,
                            is_incremental=schema.is_incremental,
                            logger=logger,
                            incremental_field=schema.sync_type_config.get("incremental_field")
                            if schema.is_incremental
                            else None,
                            incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                            if schema.is_incremental
                            else None,
                            db_incremental_field_last_value=processed_incremental_last_value
                            if schema.is_incremental
                            else None,
                        )
                    elif (
                        ExternalDataSource.Type(model.pipeline.source_type) == ExternalDataSource.Type.MSSQL
                        and str(inputs.team_id) not in settings.OLD_MSSQL_SOURCE_TEAM_IDS
                    ):
                        source = mssql_source(
                            host=tunnel.local_bind_host,
                            port=int(tunnel.local_bind_port),
                            user=user,
                            password=password,
                            database=database,
                            schema=pg_schema,
                            table_names=endpoints,
                            is_incremental=schema.is_incremental,
                            logger=logger,
                            incremental_field=schema.sync_type_config.get("incremental_field")
                            if schema.is_incremental
                            else None,
                            incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                            if schema.is_incremental
                            else None,
                            db_incremental_field_last_value=processed_incremental_last_value
                            if schema.is_incremental
                            else None,
                        )
                    else:
                        # Old MS SQL Server source
                        # TODO: remove once all teams have been moved to new source
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
                        shutdown_monitor=shutdown_monitor,
                    )

            if ExternalDataSource.Type(model.pipeline.source_type) == ExternalDataSource.Type.POSTGRES:
                source = postgres_source(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    sslmode="prefer",
                    schema=pg_schema,
                    table_names=endpoints,
                    is_incremental=schema.is_incremental,
                    logger=logger,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.is_incremental
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.is_incremental
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
                    team_id=inputs.team_id,
                )
            elif ExternalDataSource.Type(model.pipeline.source_type) == ExternalDataSource.Type.MYSQL:
                source = mysql_source(
                    host=host,
                    port=int(port),
                    user=user,
                    password=password,
                    database=database,
                    using_ssl=using_ssl,
                    schema=pg_schema,
                    table_names=endpoints,
                    is_incremental=schema.is_incremental,
                    logger=logger,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.is_incremental
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.is_incremental
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
                )
            elif (
                ExternalDataSource.Type(model.pipeline.source_type) == ExternalDataSource.Type.MSSQL
                and str(inputs.team_id) not in settings.OLD_MSSQL_SOURCE_TEAM_IDS
            ):
                source = mssql_source(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    schema=pg_schema,
                    table_names=endpoints,
                    is_incremental=schema.is_incremental,
                    logger=logger,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.is_incremental
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.is_incremental
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value if schema.is_incremental else None,
                )
            else:
                # Old MS SQL Server source
                # TODO: remove once all teams have been moved to new source
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
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.is_incremental
                    else None,
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
                shutdown_monitor=shutdown_monitor,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.SNOWFLAKE:
            from posthog.temporal.data_imports.pipelines.snowflake.snowflake import (
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
                logger=logger,
                is_incremental=schema.is_incremental,
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
                shutdown_monitor=shutdown_monitor,
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
                shutdown_monitor=shutdown_monitor,
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
                shutdown_monitor=shutdown_monitor,
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
                shutdown_monitor=shutdown_monitor,
            )
        elif model.pipeline.source_type == ExternalDataSource.Type.BIGQUERY:
            from posthog.temporal.data_imports.pipelines.bigquery.source import (
                bigquery_source,
            )
            from posthog.temporal.data_imports.pipelines.sql_database import (
                bigquery_source as sql_bigquery_source,
            )

            dataset_id = model.pipeline.job_inputs.get("dataset_id")
            project_id = model.pipeline.job_inputs.get("project_id")
            private_key = model.pipeline.job_inputs.get("private_key")
            private_key_id = model.pipeline.job_inputs.get("private_key_id")
            client_email = model.pipeline.job_inputs.get("client_email")
            token_uri = model.pipeline.job_inputs.get("token_uri")

            if not private_key:
                raise ValueError(f"Missing private key for BigQuery: '{model.id}'")

            temporary_dataset_id = model.pipeline.job_inputs.get("temporary_dataset_id")
            using_temporary_dataset = (
                model.pipeline.job_inputs.get("using_temporary_dataset", False) and temporary_dataset_id is not None
            )

            # Including the schema ID in table prefix ensures we only delete tables
            # from this schema, and that if we fail we will clean up any previous
            # execution's tables.
            # Table names in BigQuery can have up to 1024 bytes, so we can be pretty
            # relaxed with using a relatively long UUID as part of the prefix.
            # Some special characters do need to be replaced, so we use the hex
            # representation of the UUID.
            schema_id = inputs.schema_id.hex
            destination_table_prefix = f"__posthog_import_{schema_id}"

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
                if str(inputs.team_id) in settings.OLD_BIGQUERY_SOURCE_TEAM_IDS:
                    source = sql_bigquery_source(
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
                        db_incremental_field_last_value=processed_incremental_last_value
                        if schema.is_incremental
                        else None,
                    )
                else:
                    source = bigquery_source(
                        dataset_id=dataset_id,
                        project_id=project_id,
                        private_key=private_key,
                        private_key_id=private_key_id,
                        client_email=client_email,
                        token_uri=token_uri,
                        table_name=schema.name,
                        is_incremental=schema.is_incremental,
                        bq_destination_table_id=destination_table,
                        incremental_field=schema.sync_type_config.get("incremental_field")
                        if schema.is_incremental
                        else None,
                        incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                        if schema.is_incremental
                        else None,
                        db_incremental_field_last_value=processed_incremental_last_value
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
                    shutdown_monitor=shutdown_monitor,
                )
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
                shutdown_monitor=shutdown_monitor,
            )
        else:
            raise ValueError(f"Source type {model.pipeline.source_type} not supported")


def _run(
    job_inputs: PipelineInputs,
    source: DltSource | SourceResponse,
    logger: FilteringBoundLogger,
    inputs: ImportDataActivityInputs,
    schema: ExternalDataSchema,
    reset_pipeline: bool,
    shutdown_monitor: ShutdownMonitor,
):
    pipeline = PipelineNonDLT(
        source, logger, job_inputs.run_id, schema.is_incremental, reset_pipeline, shutdown_monitor
    )
    pipeline.run()
    del pipeline
