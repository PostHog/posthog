import uuid
import typing
import asyncio
import datetime as dt
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from django.conf import settings

import aioboto3
from aiobotocore.config import AioConfig
from temporalio import activity

from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import Product

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.type_defs import ObjectIdentifierTypeDef

from structlog.contextvars import bind_contextvars

from posthog.batch_exports.service import BackfillDetails, BatchExportField, BatchExportModel, BatchExportSchema
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import ClickHouseClientTimeoutError, ClickHouseQueryStatus, get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import default_fields
from products.batch_exports.backend.temporal.record_batch_model import resolve_batch_exports_model
from products.batch_exports.backend.temporal.spmc import (
    RecordBatchModel,
    compose_filters_clause,
    generate_query_ranges,
    is_5_min_batch_export,
    use_distributed_events_recent_table,
    wait_for_delta_past_data_interval_end,
)
from products.batch_exports.backend.temporal.sql import (
    EXPORT_TO_S3_FROM_DISTRIBUTED_EVENTS_RECENT,
    EXPORT_TO_S3_FROM_EVENTS,
    EXPORT_TO_S3_FROM_EVENTS_BACKFILL,
    EXPORT_TO_S3_FROM_EVENTS_RECENT,
    EXPORT_TO_S3_FROM_EVENTS_UNBOUNDED,
    EXPORT_TO_S3_FROM_PERSONS,
    EXPORT_TO_S3_FROM_PERSONS_BACKFILL,
)
from products.batch_exports.backend.temporal.utils import set_status_to_running_task

LOGGER = get_write_only_logger()


def _get_s3_endpoint_url() -> str:
    """Get the S3 endpoint URL for the Temporal worker.

    When running the stack locally, MinIO runs in Docker but the Temporal workers run outside, so we need to pass in
    localhost URL rather than the hostname of the container.
    """
    if settings.DEBUG or settings.TEST:
        return "http://localhost:19000"
    return settings.BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT


@asynccontextmanager
async def get_s3_client():
    """Async context manager for creating and managing an S3 client."""
    session = aioboto3.Session()
    async with session.client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        endpoint_url=_get_s3_endpoint_url(),
        region_name=settings.BATCH_EXPORT_OBJECT_STORAGE_REGION,
        # aiobotocore defaults keepalive_timeout to 12 seconds, which can be low for
        # slower batch exports.
        config=AioConfig(connect_timeout=60, read_timeout=300, connector_args={"keepalive_timeout": 300}),
    ) as s3_client:
        yield s3_client


async def _delete_all_from_bucket_with_prefix(bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    async with get_s3_client() as s3_client:
        response = await s3_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)
        if "Contents" in response:
            objects_to_delete: list[ObjectIdentifierTypeDef] = [
                {"Key": obj["Key"]} for obj in response["Contents"] if "Key" in obj
            ]
            if objects_to_delete:
                await s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})


@dataclass
class BatchExportInsertIntoInternalStageInputs:
    """Base dataclass for batch export insert inputs containing common fields."""

    team_id: int
    batch_export_id: str
    data_interval_start: str | None
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    run_id: str | None = None
    backfill_details: BackfillDetails | None = None
    batch_export_model: BatchExportModel | None = None
    # TODO: Remove after updating existing batch exports
    batch_export_schema: BatchExportSchema | None = None
    destination_default_fields: list[BatchExportField] | None = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        """Return a dictionary of properties that we want to log if an error is raised."""
        return {
            "team_id": self.team_id,
            "batch_export_id": self.batch_export_id,
            "data_interval_start": self.data_interval_start,
            "data_interval_end": self.data_interval_end,
            "exclude_events": self.exclude_events,
            "include_events": self.include_events,
            "run_id": self.run_id,
            "backfill_details": self.backfill_details,
            "batch_export_model": self.batch_export_model,
            "batch_export_schema": self.batch_export_schema,
            "destination_default_fields": self.destination_default_fields,
        }


@activity.defn
async def insert_into_internal_stage_activity(inputs: BatchExportInsertIntoInternalStageInputs):
    """Write record batches to our own internal S3 staging area.

    TODO - update sessions model query
    """
    bind_contextvars(
        team_id=inputs.team_id,
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    logger = LOGGER.bind()

    logger.info("Staging data for batch export")

    async with (
        Heartbeater(),
        set_status_to_running_task(run_id=inputs.run_id),
    ):
        _, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.team_id, inputs.batch_export_model, inputs.batch_export_schema, inputs.batch_export_id
        )
        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        if record_batch_model is not None:
            query_or_model = record_batch_model
            query_parameters = {}
        else:
            query, query_parameters = await _get_query(
                model_name=model_name,
                backfill_details=inputs.backfill_details,
                team_id=inputs.team_id,
                batch_export_id=inputs.batch_export_id,
                full_range=full_range,
                data_interval_start=inputs.data_interval_start,
                data_interval_end=inputs.data_interval_end,
                fields=fields,
                filters=filters,
                destination_default_fields=inputs.destination_default_fields,
                exclude_events=inputs.exclude_events,
                include_events=inputs.include_events,
                extra_query_parameters=extra_query_parameters,
            )
            query_or_model = query

        await _write_batch_export_record_batches_to_internal_stage(
            query_or_model=query_or_model,
            full_range=full_range,
            query_parameters=query_parameters,
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
        )


async def _get_query(
    model_name: str,
    backfill_details: BackfillDetails | None,
    team_id: int,
    batch_export_id: str,
    full_range: tuple[dt.datetime | None, dt.datetime],
    data_interval_start: str | None,
    data_interval_end: str,
    fields: list[BatchExportField] | None = None,
    destination_default_fields: list[BatchExportField] | None = None,
    filters: list[dict[str, str | list[str]]] | None = None,
    **parameters,
):
    logger = LOGGER.bind(model_name=model_name)

    if fields is None:
        if destination_default_fields is None:
            fields = default_fields()
        else:
            fields = destination_default_fields

    extra_query_parameters = parameters.pop("extra_query_parameters", {}) or {}

    if filters is not None and len(filters) > 0:
        filters_str, extra_query_parameters = await database_sync_to_async(compose_filters_clause)(
            filters, team_id=team_id, values=extra_query_parameters
        )
    else:
        filters_str, extra_query_parameters = "", extra_query_parameters

    is_backfill = backfill_details is not None
    # The number of partitions controls how many files ClickHouse writes to concurrently.
    num_partitions = settings.BATCH_EXPORT_CLICKHOUSE_S3_PARTITIONS

    if model_name == "persons":
        if is_backfill and full_range[0] is None:
            query_template = EXPORT_TO_S3_FROM_PERSONS_BACKFILL
        else:
            query_template = EXPORT_TO_S3_FROM_PERSONS

        query = query_template.safe_substitute(
            s3_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            s3_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            s3_folder=_get_clickhouse_s3_staging_folder_url(
                batch_export_id=batch_export_id,
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
            ),
            num_partitions=num_partitions,
        )
    else:
        if parameters.get("exclude_events", None):
            parameters["exclude_events"] = list(parameters["exclude_events"])
        else:
            parameters["exclude_events"] = []

        if parameters.get("include_events", None):
            parameters["include_events"] = list(parameters["include_events"])
        else:
            parameters["include_events"] = []

        # for 5 min batch exports we query the events_recent table, which is known to have zero replication lag, but
        # may not be able to handle the load from all batch exports
        if is_5_min_batch_export(full_range=full_range) and not is_backfill:
            logger.info("Using events_recent table for 5 min batch export")
            query_template = EXPORT_TO_S3_FROM_EVENTS_RECENT
        # for other batch exports that should use `events_recent` we use the `distributed_events_recent` table
        # which is a distributed table that sits in front of the `events_recent` table
        elif use_distributed_events_recent_table(
            is_backfill=is_backfill, backfill_details=backfill_details, data_interval_start=full_range[0]
        ):
            logger.info("Using distributed_events_recent table for batch export")
            query_template = EXPORT_TO_S3_FROM_DISTRIBUTED_EVENTS_RECENT
        elif str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
            logger.info("Using unbounded events query for batch export")
            query_template = EXPORT_TO_S3_FROM_EVENTS_UNBOUNDED
        elif is_backfill:
            logger.info("Using events_batch_export_backfill query for batch export")
            query_template = EXPORT_TO_S3_FROM_EVENTS_BACKFILL
        else:
            logger.info("Using events table for batch export")
            query_template = EXPORT_TO_S3_FROM_EVENTS
            lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS)
            parameters["lookback_days"] = lookback_days

        if "_inserted_at" not in [field["alias"] for field in fields]:
            control_fields = [BatchExportField(expression="_inserted_at", alias="_inserted_at")]
        else:
            control_fields = []

        query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

        if filters_str:
            filters_str = f"AND {filters_str}"

        query = query_template.safe_substitute(
            fields=query_fields,
            filters=filters_str,
            s3_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            s3_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            s3_folder=_get_clickhouse_s3_staging_folder_url(
                batch_export_id=batch_export_id,
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
            ),
            num_partitions=num_partitions,
        )

    parameters["team_id"] = team_id

    tags = query_tagging.get_query_tags()
    tags.team_id = team_id
    with suppress(Exception):
        tags.batch_export_id = uuid.UUID(batch_export_id)
    tags.product = Product.BATCH_EXPORT
    tags.query_type = "batch_export"
    parameters["log_comment"] = tags.to_json()

    parameters = {**parameters, **extra_query_parameters}
    return query, parameters


def get_s3_staging_folder(batch_export_id: str, data_interval_start: str | None, data_interval_end: str) -> str:
    """Get the URL for the S3 staging folder for a given batch export."""
    subfolder = "batch-exports"
    return f"{subfolder}/{batch_export_id}/{data_interval_start}-{data_interval_end}"


def _get_clickhouse_s3_staging_folder_url(
    batch_export_id: str, data_interval_start: str | None, data_interval_end: str
) -> str:
    """Get the URL for the S3 staging folder for a given batch export.

    This is passed to the ClickHouse query as the `s3_folder` parameter.
    When running the stack locally, ClickHouse and MinIO are both running in Docker so we use the hostname of the
    container.
    """
    bucket = settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET
    region = settings.BATCH_EXPORT_OBJECT_STORAGE_REGION
    # in these environments this will be a URL for MinIO
    if settings.DEBUG or settings.TEST:
        base_url = f"{settings.BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT}/{bucket}/"
    else:
        base_url = f"https://{bucket}.s3.{region}.amazonaws.com/"

    folder = get_s3_staging_folder(batch_export_id, data_interval_start, data_interval_end)
    return f"{base_url}{folder}"


async def _write_batch_export_record_batches_to_internal_stage(
    query_or_model: str | RecordBatchModel,
    full_range: tuple[dt.datetime | None, dt.datetime],
    query_parameters: dict[str, typing.Any],
    team_id: int,
    batch_export_id: str,
    data_interval_start: str | None,
    data_interval_end: str,
):
    """Write record batches to our own internal S3 staging area."""
    logger = LOGGER.bind()

    clickhouse_url = None
    # 5 min batch exports should query a single node, which is known to have zero replication lag
    if is_5_min_batch_export(full_range=full_range):
        clickhouse_url = settings.CLICKHOUSE_OFFLINE_5MIN_CLUSTER_HOST

    # Data can sometimes take a while to settle, so for 5 min batch exports we wait several seconds just to be safe.
    # For all other batch exports we wait for 1 minute since we're querying the events_recent table using a
    # distributed table and setting `max_replica_delay_for_distributed_queries` to 1 minute
    if is_5_min_batch_export(full_range):
        delta = dt.timedelta(seconds=30)
    else:
        delta = dt.timedelta(minutes=1)
    end_at = full_range[1]
    await wait_for_delta_past_data_interval_end(end_at, delta)

    done_ranges: list[tuple[dt.datetime, dt.datetime]] = []
    async with get_client(team_id=team_id, clickhouse_url=clickhouse_url) as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        # TODO - in future we might want to catch any ClickHouse memory usage errors and break down the interval into
        # sub-intervals to reduce memory usage
        for interval_start, interval_end in generate_query_ranges(full_range, done_ranges):
            if interval_start is not None:
                query_parameters["interval_start"] = interval_start.strftime("%Y-%m-%d %H:%M:%S.%f")
            query_parameters["interval_end"] = interval_end.strftime("%Y-%m-%d %H:%M:%S.%f")

            if isinstance(query_or_model, RecordBatchModel):
                s3_folder = _get_clickhouse_s3_staging_folder_url(
                    batch_export_id=batch_export_id,
                    data_interval_start=data_interval_start,
                    data_interval_end=data_interval_end,
                )
                assert settings.OBJECT_STORAGE_ACCESS_KEY_ID is not None
                assert settings.OBJECT_STORAGE_SECRET_ACCESS_KEY is not None
                query, query_parameters = await query_or_model.as_insert_into_s3_query_with_parameters(
                    data_interval_start=interval_start,
                    data_interval_end=interval_end,
                    s3_folder=s3_folder,
                    s3_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                    s3_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                    num_partitions=settings.BATCH_EXPORT_CLICKHOUSE_S3_PARTITIONS,
                )
            else:
                query = query_or_model

            s3_staging_folder = get_s3_staging_folder(
                batch_export_id=batch_export_id,
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
            )
            try:
                await _delete_all_from_bucket_with_prefix(
                    bucket_name=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix=s3_staging_folder
                )
            except Exception as e:
                logger.exception(
                    "Unexpected error occurred while deleting existing objects from internal S3 staging bucket",
                    exc_info=e,
                )
                raise

            query_id = uuid.uuid4()
            logger.info("Executing pre-export stage query", query_id=str(query_id))
            try:
                await client.execute_query(
                    query, query_parameters=query_parameters, query_id=str(query_id), timeout=300
                )
            except ClickHouseClientTimeoutError:
                logger.warning(
                    "Timed-out waiting for insert into S3. Will attempt to check query status before continuing",
                    query_id=str(query_id),
                )

                status = await client.acheck_query(str(query_id), raise_on_error=True)

                while status == ClickHouseQueryStatus.RUNNING:
                    await asyncio.sleep(10)
                    status = await client.acheck_query(str(query_id), raise_on_error=True)

            except Exception as e:
                logger.exception(
                    "Unexpected error occurred while writing record batches to internal S3 staging bucket",
                    exc_info=e,
                )
                raise
