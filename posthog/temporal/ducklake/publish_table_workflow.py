from __future__ import annotations

import json
import asyncio
import datetime as dt
from dataclasses import dataclass
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.utils import timezone

import psycopg
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy

from posthog.ducklake.common import (
    default_bucket_region,
    get_duckgres_config_for_org,
    get_org_config,
    validate_duckgres_identifier,
)
from posthog.ducklake.models import ManagedWarehousePublishedTable
from posthog.ducklake.publish import (
    build_publish_copy_sql,
    delete_stale_publish_versions,
    publish_folder,
    publish_s3_uri,
    publish_url_pattern,
    sum_publish_version_size_bytes,
)
from posthog.ducklake.storage import setup_duckgres_session
from posthog.models import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger

from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.util import S3_DELETE_TIME_BUFFER

LOGGER = get_logger(__name__)


@dataclass
class PublishTableInputs:
    team_id: int
    publication_id: str


@dataclass
class PublishCopyResult:
    folder_version: str
    row_count: int
    bucket: str
    bucket_region: str


@dataclass
class PublishRegisterInputs:
    team_id: int
    publication_id: str
    folder_version: str
    row_count: int
    bucket: str
    bucket_region: str


@dataclass
class PrunePublishedSnapshotInputs:
    team_id: int
    publication_id: str
    # A version whose COPY completed but which may not be registered as live yet —
    # kept alongside the live version so a half-finished register never strands the
    # table on a deleted folder.
    completed_version: str | None = None
    # The version the table pointed at before this publish. Kept for one prune
    # cycle so readers that resolved the old url_pattern just before the repoint
    # don't lose their files mid-query.
    superseded_version: str | None = None


@dataclass
class PublishMarkFailedInputs:
    team_id: int
    publication_id: str
    error: str


@temporalio.activity.defn
def publish_table_copy_activity(inputs: PublishTableInputs) -> PublishCopyResult:
    """Run COPY TO parquet on the org's duckgres worker, into a fresh version folder."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(publication_id=inputs.publication_id)
    close_old_connections()
    publication = ManagedWarehousePublishedTable.objects.for_team(inputs.team_id).get(
        id=inputs.publication_id, deleted=False
    )
    validate_duckgres_identifier(publication.source_schema_name)
    validate_duckgres_identifier(publication.source_table_name)

    publication.status = ManagedWarehousePublishedTable.Status.PUBLISHING
    publication.save(update_fields=["status", "updated_at"])

    team = Team.objects.only("organization_id").get(id=inputs.team_id)
    organization_id = str(team.organization_id)
    config = get_duckgres_config_for_org(organization_id)
    # Published snapshots live in the org's own managed-warehouse bucket, so the
    # worker's ambient credentials cover the write — no injected secret.
    storage = get_org_config(organization_id)
    bucket = storage.get("DUCKLAKE_BUCKET") or ""
    if not bucket:
        raise ValueError(f"No managed warehouse bucket recorded for organization {organization_id}")
    bucket_region = storage.get("DUCKLAKE_BUCKET_REGION") or default_bucket_region()

    version = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    folder = publish_folder(inputs.team_id, publication.id.hex)
    destination = publish_s3_uri(bucket, folder, version)

    with HeartbeaterSync(details=("duckgres_publish", inputs.publication_id), logger=logger):
        with psycopg.connect(
            host=config["DUCKGRES_HOST"],
            port=config["DUCKGRES_PORT"],
            dbname=config["DUCKGRES_DATABASE"],
            user=config["DUCKGRES_USERNAME"],
            password=config["DUCKGRES_PASSWORD"],
            autocommit=True,
            connect_timeout=30,
            keepalives=1,
            keepalives_idle=60,
            keepalives_interval=15,
            keepalives_count=4,
        ) as conn:
            setup_duckgres_session(conn, extensions=("httpfs",))
            # COPY TO returns the rows it copied — using it instead of a separate
            # count(*) keeps the count on the same snapshot as the copied data.
            cursor = conn.execute(
                build_publish_copy_sql(publication.source_schema_name, publication.source_table_name, destination)
            )
            row = cursor.fetchone()
            row_count = int(row[0]) if row else 0
            if row_count == 0:
                raise ValueError("Empty modeled tables cannot be published yet.")

    return PublishCopyResult(folder_version=version, row_count=row_count, bucket=bucket, bucket_region=bucket_region)


@temporalio.activity.defn
def publish_table_register_activity(inputs: PublishRegisterInputs) -> str | None:
    """Point the DataWarehouseTable at the freshly published version folder.

    Describes the new snapshot before anything commits, so readers never see new
    files through stale columns and a failed describe leaves no trace. Returns the
    version the table pointed at before this publish, so the caller can keep it
    alive for one more prune cycle.
    """
    close_old_connections()
    publication = ManagedWarehousePublishedTable.objects.for_team(inputs.team_id).get(
        id=inputs.publication_id, deleted=False
    )
    folder = publish_folder(inputs.team_id, publication.id.hex)
    url_pattern = publish_url_pattern(inputs.bucket, inputs.bucket_region, folder, inputs.folder_version)

    table: DataWarehouseTable | None = None
    if publication.table_id is not None:
        table = DataWarehouseTable.objects.filter(team_id=inputs.team_id, id=publication.table_id).first()
    if table is None:
        table = DataWarehouseTable(
            team_id=inputs.team_id,
            name=publication.name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=url_pattern,
        )
    else:
        table.format = DataWarehouseTable.TableFormat.Parquet
        table.url_pattern = url_pattern

    columns = table.get_columns()
    size_in_s3_mib = sum_publish_version_size_bytes(inputs.bucket, folder, inputs.folder_version) / (1024 * 1024)

    superseded_version = publication.folder_version
    with transaction.atomic():
        table.save()
        table.set_columns(columns)
        table.row_count = inputs.row_count
        table.size_in_s3_mib = size_in_s3_mib
        table.save()

        publication.table_id = table.id
        publication.status = ManagedWarehousePublishedTable.Status.COMPLETED
        publication.folder_version = inputs.folder_version
        publication.row_count = inputs.row_count
        publication.last_published_at = timezone.now()
        publication.last_error = None
        publication.save(
            update_fields=[
                "table_id",
                "status",
                "folder_version",
                "row_count",
                "last_published_at",
                "last_error",
                "updated_at",
            ]
        )

    return superseded_version


@temporalio.activity.defn
def prune_published_snapshot_activity(inputs: PrunePublishedSnapshotInputs) -> None:
    """Delete snapshot files the publication no longer needs.

    Keeps the live version (publication.folder_version) plus any just-completed
    version; deletes everything when the publication is deleted or has never
    published successfully. Resolves the bucket itself so it also runs standalone
    from the delete API path, where no copy result exists.
    """
    close_old_connections()
    publication = (
        ManagedWarehousePublishedTable.objects.for_team(inputs.team_id).filter(id=inputs.publication_id).first()
    )
    if publication is None:
        return

    team = Team.objects.only("organization_id").get(id=inputs.team_id)
    storage = get_org_config(str(team.organization_id))
    bucket = storage.get("DUCKLAKE_BUCKET") or ""
    if not bucket:
        raise ValueError(f"No managed warehouse bucket recorded for organization {team.organization_id}")

    keep_versions: set[str] = set()
    min_age_seconds = 0
    if not publication.deleted:
        keep_versions = {
            version
            for version in (publication.folder_version, inputs.completed_version, inputs.superseded_version)
            if version is not None
        }
        min_age_seconds = S3_DELETE_TIME_BUFFER
    delete_stale_publish_versions(
        bucket, publish_folder(inputs.team_id, publication.id.hex), keep_versions, min_age_seconds=min_age_seconds
    )


@temporalio.activity.defn
def publish_table_mark_failed_activity(inputs: PublishMarkFailedInputs) -> None:
    close_old_connections()
    ManagedWarehousePublishedTable.objects.for_team(inputs.team_id).filter(id=inputs.publication_id).update(
        status=ManagedWarehousePublishedTable.Status.FAILED,
        last_error=inputs.error[:512],
        updated_at=timezone.now(),
    )


async def _prune_published_snapshot_best_effort(inputs: PrunePublishedSnapshotInputs, warning_message: str) -> None:
    try:
        await temporalio.workflow.execute_activity(
            prune_published_snapshot_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except Exception:
        temporalio.workflow.logger.warning(warning_message)


@temporalio.workflow.defn(name="duckgres-publish-table")
class DuckgresPublishTableWorkflow(PostHogWorkflow):
    # TODO: Reap publications left in PUBLISHING when Temporal terminates or cancels a workflow.
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PublishTableInputs:
        loaded = json.loads(inputs[0])
        return PublishTableInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: PublishTableInputs) -> None:
        copy_result: PublishCopyResult | None = None
        try:
            copy_result = await temporalio.workflow.execute_activity(
                publish_table_copy_activity,
                inputs,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30)),
            )
            superseded_version = await temporalio.workflow.execute_activity(
                publish_table_register_activity,
                PublishRegisterInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    folder_version=copy_result.folder_version,
                    row_count=copy_result.row_count,
                    bucket=copy_result.bucket,
                    bucket_region=copy_result.bucket_region,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
            await _prune_published_snapshot_best_effort(
                PrunePublishedSnapshotInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    completed_version=copy_result.folder_version,
                    superseded_version=superseded_version,
                ),
                "Publish cleanup failed; stale version folders remain",
            )
        except Exception as error:
            # Prune whatever the failed run wrote: partial COPY folders always, the
            # whole folder if the publication was deleted mid-publish.
            await _prune_published_snapshot_best_effort(
                PrunePublishedSnapshotInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    completed_version=copy_result.folder_version if copy_result else None,
                ),
                "Publish failure prune failed; stale files may remain",
            )
            await temporalio.workflow.execute_activity(
                publish_table_mark_failed_activity,
                PublishMarkFailedInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    error=str(error),
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


@temporalio.workflow.defn(name="duckgres-prune-published-snapshot")
class DuckgresPrunePublishedSnapshotWorkflow(PostHogWorkflow):
    """Standalone snapshot prune, scheduled when a publication is deleted via the API."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PrunePublishedSnapshotInputs:
        loaded = json.loads(inputs[0])
        return PrunePublishedSnapshotInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: PrunePublishedSnapshotInputs) -> None:
        # Give queries that resolved the table's url_pattern just before the
        # publication was deleted time to finish before their files disappear.
        await asyncio.sleep(S3_DELETE_TIME_BUFFER)
        await temporalio.workflow.execute_activity(
            prune_published_snapshot_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
        )
