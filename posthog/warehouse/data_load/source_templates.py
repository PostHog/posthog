from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.warehouse.models.external_data_job import ExternalDataJob, get_external_data_job, get_latest_run_if_exists
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.join import DataWarehouseJoin
from posthog.warehouse.util import database_sync_to_async


@database_sync_to_async
def database_operations(team_id: int, table_prefix: str) -> None:
    customer_join_exists = DataWarehouseJoin.objects.filter(
        team_id=team_id,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name=f"{table_prefix}stripe_customer",
        joining_table_key="email",
        field_name=f"{table_prefix}stripe_customer",
    ).exists()

    invoice_join_exists = DataWarehouseJoin.objects.filter(
        team_id=team_id,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name=f"{table_prefix}stripe_invoice",
        joining_table_key="customer_email",
        field_name=f"{table_prefix}stripe_invoice",
    ).exists()

    if not customer_join_exists:
        DataWarehouseJoin.objects.create(
            team_id=team_id,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=f"{table_prefix}stripe_customer",
            joining_table_key="email",
            field_name=f"{table_prefix}stripe_customer",
        )

    if not invoice_join_exists:
        DataWarehouseJoin.objects.create(
            team_id=team_id,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=f"{table_prefix}stripe_invoice",
            joining_table_key="customer_email",
            field_name=f"{table_prefix}stripe_invoice",
        )


async def create_warehouse_templates_for_source(team_id: int, run_id: str) -> None:
    logger = await bind_temporal_worker_logger(team_id=team_id)

    job: ExternalDataJob = await get_external_data_job(job_id=run_id)
    last_successful_job: ExternalDataJob | None = await get_latest_run_if_exists(job.team_id, job.pipeline_id)

    source: ExternalDataSource.Type = job.pipeline.source_type

    # Quick exit if this isn't the first sync, or a stripe source
    if source != ExternalDataSource.Type.STRIPE or last_successful_job is not None:
        logger.info(
            f"Create warehouse templates skipped for job {run_id}",
        )
        return

    table_prefix = job.pipeline.prefix or ""

    await database_operations(team_id, table_prefix)

    logger.info(
        f"Created warehouse template for job {run_id}",
    )
