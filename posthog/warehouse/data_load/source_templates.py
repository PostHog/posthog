from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.join import DataWarehouseJoin


def database_operations(team_id: int, table_prefix: str) -> None:
    customer_join_exists = (
        DataWarehouseJoin.objects.filter(
            team_id=team_id,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=f"{table_prefix}stripe_customer",
            joining_table_key="email",
            field_name=f"{table_prefix}stripe_customer",
        )
        .exclude(deleted=True)
        .exists()
    )

    invoice_join_exists = (
        DataWarehouseJoin.objects.filter(
            team_id=team_id,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=f"{table_prefix}stripe_invoice",
            joining_table_key="customer_email",
            field_name=f"{table_prefix}stripe_invoice",
        )
        .exclude(deleted=True)
        .exists()
    )

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


def create_warehouse_templates_for_source(team_id: int, run_id: str) -> None:
    logger = bind_temporal_worker_logger_sync(team_id=team_id)

    job: ExternalDataJob = ExternalDataJob.objects.get(pk=run_id)
    last_successful_job: ExternalDataJob | None = (
        ExternalDataJob.objects.filter(
            team_id=job.team_id, pipeline_id=job.pipeline_id, status=ExternalDataJob.Status.COMPLETED
        )
        .prefetch_related("pipeline")
        .order_by("-created_at")
        .first()
    )

    source: ExternalDataSource.Type = job.pipeline.source_type

    # Quick exit if this isn't the first sync, or a stripe source
    if source != ExternalDataSource.Type.STRIPE or last_successful_job is not None:
        logger.info(
            f"Create warehouse templates skipped for job {run_id}",
        )
        return

    table_prefix = job.pipeline.prefix or ""

    database_operations(team_id, table_prefix)

    logger.info(
        f"Created warehouse template for job {run_id}",
    )
