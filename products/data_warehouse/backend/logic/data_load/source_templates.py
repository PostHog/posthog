from django.db import close_old_connections

from posthog.temporal.common.logger import get_logger

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.revenue_analytics.backend.joins import ensure_person_join
from products.warehouse_sources.backend.facade.models import ExternalDataJob
from products.warehouse_sources.backend.facade.sources import CUSTOMER_IO_WEBHOOK_SCHEMA_NAMES
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

LOGGER = get_logger(__name__)

PERSON_DISTINCT_IDS_TABLE = "person_distinct_ids"


def database_operations(team_id: int, table_prefix: str) -> None:
    DataWarehouseJoin.create_if_missing(
        team_id=team_id,
        deleted=False,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name=f"{table_prefix}stripe_customer",
        joining_table_key="email",
        field_name=f"{table_prefix}stripe_customer",
    )

    DataWarehouseJoin.create_if_missing(
        team_id=team_id,
        deleted=False,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name=f"{table_prefix}stripe_invoice",
        joining_table_key="customer_email",
        field_name=f"{table_prefix}stripe_invoice",
    )

    ensure_person_join(team_id, table_prefix)


def customer_io_operations(team_id: int, job: ExternalDataJob) -> None:
    """Join a synced Customer.io webhook table to `person_distinct_ids` on its `distinct_id` column.

    Without this join a webhook table has no path to a person, so it can't be used as an insight
    series until the user hand-writes the join. With it, `person_distinct_ids.person_id` is
    available as an aggregation target and gets picked up automatically.

    Only the webhook event tables get it — the API list endpoints (campaigns, segments, …) describe
    workspace configuration, not per-person activity.
    """
    schema = job.schema
    if schema is None or schema.name not in CUSTOMER_IO_WEBHOOK_SCHEMA_NAMES:
        return

    # The join targets the table by name, so it can only be created once the table exists — which
    # is after the first sync that carried rows.
    table = schema.table
    if table is None or table.deleted:
        return

    # Match on the table pair regardless of `deleted` or of the keys: a user who retargeted the
    # join at a different column, or soft-deleted it because they don't want it, shouldn't have it
    # reinstated behind them on the next sync.
    if DataWarehouseJoin.objects.filter(
        team_id=team_id,
        source_table_name=table.name,
        joining_table_name=PERSON_DISTINCT_IDS_TABLE,
    ).exists():
        return

    DataWarehouseJoin.objects.create(
        team_id=team_id,
        deleted=False,
        source_table_name=table.name,
        source_table_key="distinct_id",
        joining_table_name=PERSON_DISTINCT_IDS_TABLE,
        joining_table_key="distinct_id",
        field_name=PERSON_DISTINCT_IDS_TABLE,
    )


def create_warehouse_templates_for_source(team_id: int, run_id: str) -> None:
    logger = LOGGER.bind(team_id=team_id)
    close_old_connections()

    # nosemgrep: idor-lookup-without-team (internal Temporal activity, not API-exposed)
    job: ExternalDataJob = ExternalDataJob.objects.select_related("pipeline", "schema__table").get(pk=run_id)
    source = ExternalDataSourceType(job.pipeline.source_type)

    # Customer.io wires up its join per webhook schema, so unlike Stripe it runs on every sync
    # rather than only the first one — each schema's table appears the first time it syncs rows.
    if source == ExternalDataSourceType.CUSTOMERIO:
        customer_io_operations(team_id, job)
        logger.info(f"Ensured Customer.io warehouse templates for job {run_id}")
        return

    last_successful_job: ExternalDataJob | None = (
        ExternalDataJob.objects.filter(
            team_id=job.team_id, pipeline_id=job.pipeline_id, status=ExternalDataJob.Status.COMPLETED
        )
        .prefetch_related("pipeline")
        .order_by("-created_at")
        .first()
    )

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
