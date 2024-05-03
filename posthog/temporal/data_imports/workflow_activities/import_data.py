import dataclasses
import datetime as dt
import uuid

from dlt.common.schema.typing import TSchemaTables
from temporalio import activity

# TODO: remove dependency
from posthog.temporal.data_imports.pipelines.helpers import aupdate_job_count
from posthog.temporal.data_imports.pipelines.zendesk.credentials import ZendeskCredentialsToken

from posthog.temporal.data_imports.pipelines.pipeline import DataImportPipeline, PipelineInputs
from posthog.utils import get_instance_region
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSource,
    get_external_data_job,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger
import asyncio
from django.utils import timezone

from posthog.warehouse.models.external_data_schema import ExternalDataSchema, aget_schema_by_id


@dataclasses.dataclass
class ImportDataActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str


@activity.defn
async def import_data_activity(inputs: ImportDataActivityInputs) -> tuple[TSchemaTables, dict[str, int]]:  # noqa: F821
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
        dataset_name=model.folder_path,
    )

    schema: ExternalDataSchema = await aget_schema_by_id(inputs.schema_id, inputs.team_id)

    endpoints = [schema.name]

    source = None
    if model.pipeline.source_type == ExternalDataSource.Type.STRIPE:
        from posthog.temporal.data_imports.pipelines.stripe.helpers import stripe_source

        stripe_secret_key = model.pipeline.job_inputs.get("stripe_secret_key", None)
        account_id = model.pipeline.job_inputs.get("stripe_account_id", None)
        # Cludge: account_id should be checked here too but can deal with nulls
        # until we require re update of account_ids in stripe so they're all store
        if not stripe_secret_key:
            raise ValueError(f"Stripe secret key not found for job {model.id}")

        # Hacky just for specific user
        region = get_instance_region()
        if region == "EU" and inputs.team_id == 11870:
            start_date = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + dt.timedelta(weeks=5)
        else:
            start_date = None
            end_date = None

        source = stripe_source(
            api_key=stripe_secret_key,
            account_id=account_id,
            endpoints=tuple(endpoints),
            team_id=inputs.team_id,
            job_id=inputs.run_id,
            schema_id=str(inputs.schema_id),
            start_date=start_date,
            end_date=end_date,
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.HUBSPOT:
        from posthog.temporal.data_imports.pipelines.hubspot.auth import refresh_access_token
        from posthog.temporal.data_imports.pipelines.hubspot import hubspot

        hubspot_access_code = model.pipeline.job_inputs.get("hubspot_secret_key", None)
        refresh_token = model.pipeline.job_inputs.get("hubspot_refresh_token", None)
        if not refresh_token:
            raise ValueError(f"Hubspot refresh token not found for job {model.id}")

        if not hubspot_access_code:
            hubspot_access_code = refresh_access_token(refresh_token)

        source = hubspot(
            api_key=hubspot_access_code,
            refresh_token=refresh_token,
            endpoints=tuple(endpoints),
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.POSTGRES:
        from posthog.temporal.data_imports.pipelines.postgres import postgres_source

        host = model.pipeline.job_inputs.get("host")
        port = model.pipeline.job_inputs.get("port")
        user = model.pipeline.job_inputs.get("user")
        password = model.pipeline.job_inputs.get("password")
        database = model.pipeline.job_inputs.get("database")
        pg_schema = model.pipeline.job_inputs.get("schema")

        source = postgres_source(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            sslmode="prefer",
            schema=pg_schema,
            table_names=endpoints,
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.ZENDESK:
        from posthog.temporal.data_imports.pipelines.zendesk.helpers import zendesk_support

        # NOTE: this line errors on CI mypy but not locally. Putting arguments within the function causes the opposite error
        credentials = ZendeskCredentialsToken(
            token=model.pipeline.job_inputs.get("zendesk_api_key"),
            subdomain=model.pipeline.job_inputs.get("zendesk_subdomain"),
            email=model.pipeline.job_inputs.get("zendesk_email_address"),
        )

        data_support = zendesk_support(credentials=credentials, endpoints=tuple(endpoints), team_id=inputs.team_id)
        # Uncomment to support zendesk chat and talk
        # data_chat = zendesk_chat()
        # data_talk = zendesk_talk()

        source = data_support
    else:
        raise ValueError(f"Source type {model.pipeline.source_type} not supported")

    # Temp background heartbeat for now
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(10)
            activity.heartbeat()

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        table_row_counts = await DataImportPipeline(job_inputs, source, logger, schema.is_incremental).run()
        total_rows_synced = sum(table_row_counts.values())

        await aupdate_job_count(inputs.run_id, inputs.team_id, total_rows_synced)
    finally:
        heartbeat_task.cancel()
        await asyncio.wait([heartbeat_task])

    return source.schema.tables, table_row_counts
