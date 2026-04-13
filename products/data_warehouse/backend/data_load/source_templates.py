from django.db import close_old_connections

from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.joins import ensure_person_join

LOGGER = get_logger(__name__)


def database_operations(team_id: int, table_prefix: str) -> None:
    DataWarehouseJoin.objects.get_or_create(
        team_id=team_id,
        deleted=False,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name=f"{table_prefix}stripe_customer",
        joining_table_key="email",
        field_name=f"{table_prefix}stripe_customer",
    )

    DataWarehouseJoin.objects.get_or_create(
        team_id=team_id,
        deleted=False,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name=f"{table_prefix}stripe_invoice",
        joining_table_key="customer_email",
        field_name=f"{table_prefix}stripe_invoice",
    )

    ensure_person_join(team_id, table_prefix)


def create_warehouse_templates_for_source(team_id: int, run_id: str) -> None:
    logger = LOGGER.bind(team_id=team_id)
    close_old_connections()

    # nosemgrep: idor-lookup-without-team (internal Temporal activity, not API-exposed)
    job: ExternalDataJob = ExternalDataJob.objects.get(pk=run_id)
    last_successful_job: ExternalDataJob | None = (
        ExternalDataJob.objects.filter(
            team_id=job.team_id, pipeline_id=job.pipeline_id, status=ExternalDataJob.Status.COMPLETED
        )
        .prefetch_related("pipeline")
        .order_by("-created_at")
        .first()
    )

    source: ExternalDataSourceType = job.pipeline.source_type

    # Quick exit if this isn't the first sync, or a stripe source
    if source != ExternalDataSourceType.STRIPE or last_successful_job is not None:
        logger.info(
            f"Create warehouse templates skipped for job {run_id}",
        )
        return

    table_prefix = job.pipeline.prefix or ""

    database_operations(team_id, table_prefix)

    logger.info(
        f"Created warehouse template for job {run_id}",
    )
