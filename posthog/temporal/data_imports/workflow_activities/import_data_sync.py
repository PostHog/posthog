import dataclasses
import uuid
from datetime import datetime
from typing import Any, Optional

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
from posthog.temporal.data_imports.row_tracking import setup_row_tracking
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema, process_incremental_value
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


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
        setup_row_tracking(inputs.team_id, inputs.schema_id)

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
        processed_incremental_earliest_value = None

        if reset_pipeline is not True:
            processed_incremental_last_value = process_incremental_value(
                schema.sync_type_config.get("incremental_field_last_value"),
                schema.sync_type_config.get("incremental_field_type"),
            )
            processed_incremental_earliest_value = process_incremental_value(
                schema.incremental_field_earliest_value,
                schema.incremental_field_type,
            )

        if schema.should_use_incremental_field:
            logger.debug(f"Incremental last value being used is: {processed_incremental_last_value}")

        if processed_incremental_earliest_value:
            logger.debug(f"Incremental earliest value being used is: {processed_incremental_earliest_value}")

        source: DltSource | SourceResponse

        if model.pipeline.source_type == ExternalDataSource.Type.STRIPE:
            from posthog.temporal.data_imports.pipelines.stripe import stripe_source_v2

            stripe_secret_key = model.pipeline.job_inputs.get("stripe_secret_key", None)
            account_id = model.pipeline.job_inputs.get("stripe_account_id", None)
            if not stripe_secret_key:
                raise ValueError(f"Stripe secret key not found for job {model.id}")

            source = stripe_source_v2(
                api_key=stripe_secret_key,
                account_id=account_id,
                endpoint=schema.name,
                should_use_incremental_field=schema.should_use_incremental_field,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
                db_incremental_field_earliest_value=processed_incremental_earliest_value
                if schema.should_use_incremental_field
                else None,
                logger=logger,
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
                logger=logger,
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
        elif model.pipeline.source_type == ExternalDataSource.Type.POSTGRES:
            from posthog.temporal.data_imports.pipelines.postgres import (
                PostgreSQLSourceConfig,
                postgres_source,
            )

            pg_config = PostgreSQLSourceConfig.from_dict(model.pipeline.job_inputs)

            if pg_config.ssh_tunnel and pg_config.ssh_tunnel.enabled:
                ssh_tunnel = SSHTunnel.from_config(pg_config.ssh_tunnel)
                with ssh_tunnel.get_tunnel(pg_config.host, pg_config.port) as tunnel:
                    # TODO: Move exception handling to SSHTunnel
                    if tunnel is None:
                        raise Exception("Can't open tunnel to SSH server")

                    source = postgres_source(
                        host=tunnel.local_bind_host,
                        port=tunnel.local_bind_port,
                        user=pg_config.user,
                        password=pg_config.password,
                        database=pg_config.database,
                        sslmode="prefer",
                        schema=pg_config.schema,
                        table_names=endpoints,
                        should_use_incremental_field=schema.should_use_incremental_field,
                        logger=logger,
                        incremental_field=schema.sync_type_config.get("incremental_field")
                        if schema.should_use_incremental_field
                        else None,
                        incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                        if schema.should_use_incremental_field
                        else None,
                        db_incremental_field_last_value=processed_incremental_last_value
                        if schema.should_use_incremental_field
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
                        shutdown_monitor=shutdown_monitor,
                    )
            else:
                source = postgres_source(
                    host=pg_config.host,
                    port=pg_config.port,
                    user=pg_config.user,
                    password=pg_config.password,
                    database=pg_config.database,
                    sslmode="prefer",
                    schema=pg_config.schema,
                    table_names=endpoints,
                    should_use_incremental_field=schema.should_use_incremental_field,
                    logger=logger,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.should_use_incremental_field
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.should_use_incremental_field
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value
                    if schema.should_use_incremental_field
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
                    shutdown_monitor=shutdown_monitor,
                )

        elif model.pipeline.source_type == ExternalDataSource.Type.MYSQL:
            from posthog.temporal.data_imports.pipelines.mysql import MySQLSourceConfig, mysql_source

            mysql_config = MySQLSourceConfig.from_dict(model.pipeline.job_inputs)

            if mysql_config.ssh_tunnel and mysql_config.ssh_tunnel.enabled:
                ssh_tunnel = SSHTunnel.from_config(mysql_config.ssh_tunnel)
                with ssh_tunnel.get_tunnel(mysql_config.host, mysql_config.port) as tunnel:
                    # TODO: Move exception handling to SSHTunnel
                    if tunnel is None:
                        raise Exception("Can't open tunnel to SSH server")

                    source = mysql_source(
                        host=tunnel.local_bind_host,
                        port=tunnel.local_bind_port,
                        user=mysql_config.user,
                        password=mysql_config.password,
                        database=mysql_config.database,
                        using_ssl=mysql_config.using_ssl,
                        schema=mysql_config.schema,
                        table_names=endpoints,
                        should_use_incremental_field=schema.should_use_incremental_field,
                        logger=logger,
                        incremental_field=schema.sync_type_config.get("incremental_field")
                        if schema.should_use_incremental_field
                        else None,
                        incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                        if schema.should_use_incremental_field
                        else None,
                        db_incremental_field_last_value=processed_incremental_last_value
                        if schema.should_use_incremental_field
                        else None,
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
                source = mysql_source(
                    host=mysql_config.host,
                    port=mysql_config.port,
                    user=mysql_config.user,
                    password=mysql_config.password,
                    database=mysql_config.database,
                    using_ssl=mysql_config.using_ssl,
                    schema=mysql_config.schema,
                    table_names=endpoints,
                    should_use_incremental_field=schema.should_use_incremental_field,
                    logger=logger,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.should_use_incremental_field
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.should_use_incremental_field
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value
                    if schema.should_use_incremental_field
                    else None,
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
            ExternalDataSource.Type.MSSQL,
        ]:
            from posthog.temporal.data_imports.pipelines.mssql.mssql import MSSQLSourceConfig, mssql_source

            mssql_config = MSSQLSourceConfig.from_dict(model.pipeline.job_inputs)

            if mssql_config.ssh_tunnel and mssql_config.ssh_tunnel.enabled:
                ssh_tunnel = SSHTunnel.from_config(mssql_config.ssh_tunnel)

                with ssh_tunnel.get_tunnel(mssql_config.host, mssql_config.port) as tunnel:
                    if tunnel is None:
                        raise Exception("Can't open tunnel to SSH server")

                    source = mssql_source(
                        host=tunnel.local_bind_host,
                        port=int(tunnel.local_bind_port),
                        user=mssql_config.user,
                        password=mssql_config.password,
                        database=mssql_config.database,
                        schema=mssql_config.schema,
                        table_names=endpoints,
                        should_use_incremental_field=schema.should_use_incremental_field,
                        logger=logger,
                        incremental_field=schema.sync_type_config.get("incremental_field")
                        if schema.should_use_incremental_field
                        else None,
                        incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                        if schema.should_use_incremental_field
                        else None,
                        db_incremental_field_last_value=processed_incremental_last_value
                        if schema.should_use_incremental_field
                        else None,
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

            source = mssql_source(
                host=mssql_config.host,
                port=mssql_config.port,
                user=mssql_config.user,
                password=mssql_config.password,
                database=mssql_config.database,
                schema=mssql_config.schema,
                table_names=endpoints,
                should_use_incremental_field=schema.should_use_incremental_field,
                logger=logger,
                incremental_field=schema.sync_type_config.get("incremental_field")
                if schema.should_use_incremental_field
                else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.should_use_incremental_field
                else None,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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
                SnowflakeSourceConfig,
                snowflake_source,
            )

            snow_config = SnowflakeSourceConfig.from_dict(model.pipeline.job_inputs)

            source = snowflake_source(
                account_id=snow_config.account_id,
                auth_type=snow_config.auth_type,
                user=snow_config.user,
                password=snow_config.password,
                private_key=snow_config.private_key,
                passphrase=snow_config.passphrase,
                database=snow_config.database,
                schema=snow_config.schema,
                warehouse=snow_config.warehouse,
                role=snow_config.role,
                table_names=endpoints,
                logger=logger,
                should_use_incremental_field=schema.should_use_incremental_field,
                incremental_field=schema.sync_type_config.get("incremental_field")
                if schema.should_use_incremental_field
                else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.should_use_incremental_field
                else None,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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

            salesforce_instance_url = integration.config.get("instance_url")

            if not salesforce_access_token:
                salesforce_access_token = salesforce_refresh_access_token(
                    salesforce_refresh_token, salesforce_instance_url
                )

            source = salesforce_source(
                instance_url=salesforce_instance_url,
                access_token=salesforce_access_token,
                refresh_token=salesforce_refresh_token,
                endpoint=schema.name,
                team_id=inputs.team_id,
                job_id=inputs.run_id,
                should_use_incremental_field=schema.should_use_incremental_field,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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
                should_use_incremental_field=schema.should_use_incremental_field,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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
                should_use_incremental_field=schema.should_use_incremental_field,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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
            from posthog.temporal.data_imports.pipelines.bigquery import (
                BigQuerySourceConfig,
                bigquery_source,
            )

            bq_config = BigQuerySourceConfig.from_dict(model.pipeline.job_inputs)

            if not bq_config.private_key:
                raise ValueError(f"Missing private key for BigQuery: '{model.id}'")

            using_temporary_dataset = bq_config.using_temporary_dataset and bq_config.temporary_dataset_id is not None

            # Including the schema ID in table prefix ensures we only delete tables
            # from this schema, and that if we fail we will clean up any previous
            # execution's tables.
            # Table names in BigQuery can have up to 1024 bytes, so we can be pretty
            # relaxed with using a relatively long UUID as part of the prefix.
            # Some special characters do need to be replaced, so we use the hex
            # representation of the UUID.
            schema_id = inputs.schema_id.hex
            destination_table_prefix = f"__posthog_import_{schema_id}"

            destination_table_dataset_id = (
                bq_config.temporary_dataset_id if using_temporary_dataset else bq_config.dataset_id
            )
            destination_table = f"{bq_config.project_id}.{destination_table_dataset_id}.{destination_table_prefix}{inputs.run_id}_{str(datetime.now().timestamp()).replace('.', '')}"

            delete_all_temp_destination_tables(
                dataset_id=bq_config.dataset_id,
                table_prefix=destination_table_prefix,
                project_id=bq_config.project_id,
                dataset_project_id=bq_config.dataset_project_id,
                private_key=bq_config.private_key,
                private_key_id=bq_config.private_key_id,
                client_email=bq_config.client_email,
                token_uri=bq_config.token_uri,
                logger=logger,
            )

            try:
                source = bigquery_source(
                    dataset_id=bq_config.dataset_id,
                    project_id=bq_config.project_id,
                    dataset_project_id=bq_config.dataset_project_id,
                    private_key=bq_config.private_key,
                    private_key_id=bq_config.private_key_id,
                    client_email=bq_config.client_email,
                    token_uri=bq_config.token_uri,
                    table_name=schema.name,
                    should_use_incremental_field=schema.should_use_incremental_field,
                    logger=logger,
                    bq_destination_table_id=destination_table,
                    incremental_field=schema.sync_type_config.get("incremental_field")
                    if schema.should_use_incremental_field
                    else None,
                    incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                    if schema.should_use_incremental_field
                    else None,
                    db_incremental_field_last_value=processed_incremental_last_value
                    if schema.should_use_incremental_field
                    else None,
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
            finally:
                # Delete the destination table (if it exists) after we're done with it
                delete_table(
                    table_id=destination_table,
                    project_id=bq_config.project_id,
                    private_key=bq_config.private_key,
                    private_key_id=bq_config.private_key_id,
                    client_email=bq_config.client_email,
                    token_uri=bq_config.token_uri,
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
                should_use_incremental_field=schema.should_use_incremental_field,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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
        elif model.pipeline.source_type == ExternalDataSource.Type.GOOGLEADS:
            from posthog.temporal.data_imports.pipelines.google_ads import (
                GoogleAdsServiceAccountSourceConfig,
                google_ads_source,
            )

            config = GoogleAdsServiceAccountSourceConfig.from_dict(
                {**model.pipeline.job_inputs, **{"resource_name": schema.name}}
            )
            source = google_ads_source(
                config,
                should_use_incremental_field=schema.should_use_incremental_field,
                incremental_field=schema.sync_type_config.get("incremental_field")
                if schema.should_use_incremental_field
                else None,
                incremental_field_type=schema.sync_type_config.get("incremental_field_type")
                if schema.should_use_incremental_field
                else None,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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

        elif model.pipeline.source_type == ExternalDataSource.Type.TEMPORALIO:
            from posthog.temporal.data_imports.pipelines.temporalio.source import (
                TemporalIOResource,
                TemporalIOSourceConfig,
                temporalio_source,
            )

            temporal_config = TemporalIOSourceConfig.from_dict(model.pipeline.job_inputs)
            source = temporalio_source(
                temporal_config,
                TemporalIOResource(schema.name),
                should_use_incremental_field=schema.should_use_incremental_field,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
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
        elif model.pipeline.source_type == ExternalDataSource.Type.DOIT:
            from posthog.temporal.data_imports.pipelines.doit.source import (
                DoItSourceConfig,
                doit_source,
            )

            doit_config = DoItSourceConfig.from_dict(model.pipeline.job_inputs)
            source = doit_source(
                doit_config,
                schema.name,
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
        source, logger, job_inputs.run_id, schema.should_use_incremental_field, reset_pipeline, shutdown_monitor
    )
    pipeline.run()
    del pipeline
