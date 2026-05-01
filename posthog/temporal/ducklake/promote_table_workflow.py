"""Temporal workflow that extracts a managed-warehouse DuckLake table to parquet
in the customer's bucket and registers it as a queryable ``DataWarehouseTable``.

v1 is full-refresh only. Each run writes parquet to a fresh ``run_<id>/`` folder
and atomically swaps the ``DataWarehouseTable.url_pattern`` once the COPY succeeds,
then cleans up the previous run's folder.
"""

from __future__ import annotations

import json
import uuid
import typing
import datetime as dt
import dataclasses

from django.utils import timezone

import psycopg
from psycopg import sql as psql
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.ducklake.common import (
    _get_org_id_for_team,
    get_duckgres_server_for_organization,
    get_ducklake_catalog_for_organization,
)
from posthog.ducklake.storage import cleanup_staged_files, connect_to_duckgres, setup_duckgres_session
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)

PROMOTED_TABLE_S3_PREFIX = "__posthog_promoted"


@dataclasses.dataclass
class PromoteTableInputs:
    team_id: int
    promoted_table_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_id": self.team_id, "promoted_table_id": self.promoted_table_id}


@dataclasses.dataclass
class PromoteTableMetadata:
    team_id: int
    promoted_table_id: str
    source_schema_name: str
    source_table_name: str
    catalog_bucket: str
    catalog_region: str
    catalog_role_arn: str
    catalog_external_id: str
    destination_uri: str
    destination_url_pattern: str
    previous_url_pattern: str | None


@dataclasses.dataclass
class PromoteTableCopyResult:
    row_count: int
    size_in_s3_mib: float | None


def _build_destination_uri(catalog_bucket: str, team_id: int, promoted_table_id: str, run_id: str) -> str:
    return f"s3://{catalog_bucket}/{PROMOTED_TABLE_S3_PREFIX}/team_{team_id}/{promoted_table_id}/run_{run_id}/"


def _build_url_pattern(destination_uri: str) -> str:
    return f"{destination_uri.rstrip('/')}/*.parquet"


def _previous_run_uri(url_pattern: str) -> str | None:
    """Extract the directory portion from a previously-stored url_pattern."""
    if not url_pattern:
        return None
    if "/*" in url_pattern:
        return url_pattern.split("/*", 1)[0] + "/"
    return None


@activity.defn
async def prepare_promote_table_activity(inputs: PromoteTableInputs) -> PromoteTableMetadata:
    """Resolve source/destination metadata and mark the promoted table as running."""
    bind_contextvars(team_id=inputs.team_id, promoted_table_id=inputs.promoted_table_id)
    logger = LOGGER.bind()

    from products.data_warehouse.backend.models import ManagedWarehousePromotedTable

    @database_sync_to_async
    def _load_and_mark_running() -> tuple[str, str, str, str, str, str, str, str, str]:
        promoted = ManagedWarehousePromotedTable.objects.select_related("team").get(
            id=inputs.promoted_table_id, team_id=inputs.team_id, deleted=False
        )
        org_id = _get_org_id_for_team(inputs.team_id)
        catalog = get_ducklake_catalog_for_organization(org_id)
        if catalog is None:
            raise ApplicationError(f"No DuckLakeCatalog configured for team {inputs.team_id}", non_retryable=True)

        promoted.status = ManagedWarehousePromotedTable.Status.RUNNING
        promoted.last_run_started_at = timezone.now()
        promoted.last_error = None
        promoted.save(update_fields=["status", "last_run_started_at", "last_error", "updated_at"])

        return (
            str(promoted.id),
            promoted.source_schema_name,
            promoted.source_table_name,
            catalog.bucket,
            catalog.bucket_region or "us-east-1",
            catalog.cross_account_role_arn,
            catalog.cross_account_external_id,
            promoted.last_url_pattern or "",
            org_id,
        )

    (
        promoted_id,
        source_schema,
        source_table,
        catalog_bucket,
        catalog_region,
        role_arn,
        external_id,
        previous_url_pattern,
        _org_id,
    ) = await _load_and_mark_running()

    run_id = activity.info().workflow_run_id or uuid.uuid4().hex
    destination_uri = _build_destination_uri(catalog_bucket, inputs.team_id, promoted_id, run_id)
    destination_url_pattern = _build_url_pattern(destination_uri)

    await logger.ainfo(
        "Prepared promote-table metadata",
        source_schema=source_schema,
        source_table=source_table,
        destination_uri=destination_uri,
    )

    return PromoteTableMetadata(
        team_id=inputs.team_id,
        promoted_table_id=promoted_id,
        source_schema_name=source_schema,
        source_table_name=source_table,
        catalog_bucket=catalog_bucket,
        catalog_region=catalog_region,
        catalog_role_arn=role_arn,
        catalog_external_id=external_id,
        destination_uri=destination_uri,
        destination_url_pattern=destination_url_pattern,
        previous_url_pattern=previous_url_pattern or None,
    )


def _execute_copy_to_parquet(
    conn: psycopg.Connection,
    schema_name: str,
    table_name: str,
    destination_uri: str,
) -> int:
    """Run the COPY and return the source row count.

    The COPY runs against the customer's duckgres (DuckDB-over-Postgres-protocol)
    instance, which already holds credentials for its own catalog bucket — so no
    additional ``CREATE SECRET`` is needed.
    """
    qualified = psql.Identifier(schema_name, table_name)

    with conn.cursor() as cur:
        cur.execute(psql.SQL("SELECT count(*) FROM {}").format(qualified))
        row = cur.fetchone()
        row_count = int(row[0]) if row and row[0] is not None else 0

        copy_sql = psql.SQL("COPY (SELECT * FROM {}) TO {} (FORMAT PARQUET, PER_THREAD_OUTPUT TRUE)").format(
            qualified, psql.Literal(destination_uri)
        )
        cur.execute(copy_sql)

    return row_count


@activity.defn
def copy_to_parquet_activity(metadata: PromoteTableMetadata) -> PromoteTableCopyResult:
    """Run the COPY against the customer's duckgres into their bucket."""
    bind_contextvars(team_id=metadata.team_id, promoted_table_id=metadata.promoted_table_id)
    logger = LOGGER.bind()

    heartbeater = HeartbeaterSync(details=("promote_copy", metadata.promoted_table_id), logger=logger)
    with heartbeater:
        org_id = _get_org_id_for_team(metadata.team_id)
        server = get_duckgres_server_for_organization(org_id)
        if server is None:
            raise ApplicationError(f"No DuckgresServer configured for team {metadata.team_id}", non_retryable=True)

        logger.info(
            "Running COPY to parquet",
            schema=metadata.source_schema_name,
            table=metadata.source_table_name,
            destination=metadata.destination_uri,
        )

        with connect_to_duckgres(server) as conn:
            setup_duckgres_session(conn)
            row_count = _execute_copy_to_parquet(
                conn,
                metadata.source_schema_name,
                metadata.source_table_name,
                metadata.destination_uri,
            )

        logger.info("COPY completed", row_count=row_count)
        return PromoteTableCopyResult(row_count=row_count, size_in_s3_mib=None)


@activity.defn
async def finalize_promotion_activity(metadata: PromoteTableMetadata, copy_result: PromoteTableCopyResult) -> None:
    """Upsert the DataWarehouseTable, hydrate columns, mark the promotion completed."""
    bind_contextvars(team_id=metadata.team_id, promoted_table_id=metadata.promoted_table_id)
    logger = LOGGER.bind()

    @database_sync_to_async
    def _finalize() -> None:
        from products.data_warehouse.backend.models import (
            DataWarehouseCredential,
            DataWarehouseTable,
            ManagedWarehousePromotedTable,
        )

        promoted = ManagedWarehousePromotedTable.objects.select_related("team", "data_warehouse_table").get(
            id=metadata.promoted_table_id, team_id=metadata.team_id
        )

        # TODO(managed-warehouse): replace placeholder credential with the customer's
        # bucket access key/secret once managed-warehouse provisioning issues per-customer
        # IAM users. Until then, the DataWarehouseTable will not be queryable through
        # ClickHouse — column introspection (get_columns) below will fail silently.
        credential = promoted.data_warehouse_table.credential if promoted.data_warehouse_table else None
        if credential is None:
            credential = DataWarehouseCredential.objects.create(
                team=promoted.team,
                access_key="",
                access_secret="",
            )

        table_name = f"managed_warehouse_{metadata.source_schema_name}_{metadata.source_table_name}"

        if promoted.data_warehouse_table is not None:
            table = promoted.data_warehouse_table
            table.url_pattern = metadata.destination_url_pattern
            table.format = DataWarehouseTable.TableFormat.Parquet
            table.row_count = copy_result.row_count
            table.credential = credential
            table.save(update_fields=["url_pattern", "format", "row_count", "credential", "updated_at"])
        else:
            table = DataWarehouseTable.objects.create(
                team=promoted.team,
                name=table_name,
                format=DataWarehouseTable.TableFormat.Parquet,
                url_pattern=metadata.destination_url_pattern,
                credential=credential,
                row_count=copy_result.row_count,
            )
            promoted.data_warehouse_table = table

        try:
            columns = table.get_columns(safe_expose_ch_error=False)
            table.columns = {
                name: {"clickhouse": col["clickhouse"], "hogql": col["hogql"], "valid": col.get("valid", True)}
                for name, col in columns.items()
            }
            table.save(update_fields=["columns", "updated_at"])
        except Exception as exc:
            # Expected today while the credential placeholder is in place; log and continue.
            LOGGER.bind(team_id=metadata.team_id).warning(
                "Skipping column hydration for promoted table", error=str(exc)
            )

        promoted.status = ManagedWarehousePromotedTable.Status.COMPLETED
        promoted.last_synced_at = timezone.now()
        promoted.last_error = None
        promoted.row_count = copy_result.row_count
        promoted.last_url_pattern = metadata.destination_url_pattern
        promoted.save(
            update_fields=[
                "data_warehouse_table",
                "status",
                "last_synced_at",
                "last_error",
                "row_count",
                "last_url_pattern",
                "updated_at",
            ]
        )

    await _finalize()
    await logger.ainfo("Finalized promoted table")


@dataclasses.dataclass
class CleanupPreviousRunInputs:
    team_id: int
    catalog_role_arn: str
    catalog_external_id: str
    previous_run_uri: str


@activity.defn
def cleanup_previous_run_activity(inputs: CleanupPreviousRunInputs) -> None:
    """Best-effort delete of a prior run's parquet folder."""
    bind_contextvars(team_id=inputs.team_id)
    try:
        cleanup_staged_files(
            staging_uri=inputs.previous_run_uri,
            role_arn=inputs.catalog_role_arn,
            external_id=inputs.catalog_external_id,
        )
    except Exception as exc:
        LOGGER.bind(team_id=inputs.team_id).warning("Failed to clean up previous promoted-table run", error=str(exc))


@dataclasses.dataclass
class MarkFailureInputs:
    team_id: int
    promoted_table_id: str
    error_message: str


@activity.defn
async def mark_promotion_failed_activity(inputs: MarkFailureInputs) -> None:
    """Set status=failed + last_error on the promoted table after a workflow error."""
    from products.data_warehouse.backend.models import ManagedWarehousePromotedTable

    @database_sync_to_async
    def _mark() -> None:
        ManagedWarehousePromotedTable.objects.filter(id=inputs.promoted_table_id, team_id=inputs.team_id).update(
            status=ManagedWarehousePromotedTable.Status.FAILED,
            last_error=inputs.error_message[:5000],
            updated_at=timezone.now(),
        )

    await _mark()


@workflow.defn(name="ducklake-promote-table")
class DuckLakePromoteTableWorkflow(PostHogWorkflow):
    """Extract a customer's DuckLake table to parquet on a recurring schedule."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PromoteTableInputs:
        loaded = json.loads(inputs[0])
        return PromoteTableInputs(
            team_id=loaded["team_id"],
            promoted_table_id=loaded["promoted_table_id"],
        )

    @workflow.run
    async def run(self, inputs: PromoteTableInputs) -> None:
        logger = workflow.logger
        logger.info("Starting DuckLakePromoteTableWorkflow", extra=inputs.properties_to_log)

        try:
            metadata = await workflow.execute_activity(
                prepare_promote_table_activity,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            copy_result = await workflow.execute_activity(
                copy_to_parquet_activity,
                metadata,
                start_to_close_timeout=dt.timedelta(hours=2),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            await workflow.execute_activity(
                finalize_promotion_activity,
                args=[metadata, copy_result],
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            previous_run_uri = _previous_run_uri(metadata.previous_url_pattern or "")
            if previous_run_uri and previous_run_uri.rstrip("/") != metadata.destination_uri.rstrip("/"):
                await workflow.execute_activity(
                    cleanup_previous_run_activity,
                    CleanupPreviousRunInputs(
                        team_id=inputs.team_id,
                        catalog_role_arn=metadata.catalog_role_arn,
                        catalog_external_id=metadata.catalog_external_id,
                        previous_run_uri=previous_run_uri,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
        except Exception as exc:
            try:
                await workflow.execute_activity(
                    mark_promotion_failed_activity,
                    MarkFailureInputs(
                        team_id=inputs.team_id,
                        promoted_table_id=inputs.promoted_table_id,
                        error_message=str(exc),
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                workflow.logger.exception("Failed to record promotion failure")
            raise
