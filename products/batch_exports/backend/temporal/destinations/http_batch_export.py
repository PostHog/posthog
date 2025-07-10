import asyncio
import dataclasses
import datetime as dt
import io
import json

import aiohttp
from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    HttpBatchExportInputs,
)
from posthog.models import BatchExportRun
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import bind_temporal_worker_logger
from products.batch_exports.backend.temporal.batch_exports import (
    FinishBatchExportRunInputs,
    RecordsCompleted,
    StartBatchExportRunInputs,
    execute_batch_export_insert_activity,
    get_data_interval,
    iter_records,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from products.batch_exports.backend.temporal.temporary_file import (
    BatchExportTemporaryFile,
    json_dumps_bytes,
)


class RetryableResponseError(Exception):
    """Error for HTTP status >=500 (plus 429)."""

    def __init__(self, status):
        super().__init__(f"RetryableResponseError status: {status}")


class NonRetryableResponseError(Exception):
    """Error for HTTP status >= 400 and < 500 (excluding 429)."""

    def __init__(self, status, content):
        super().__init__(f"NonRetryableResponseError (status: {status}): {content}")


async def raise_for_status(response: aiohttp.ClientResponse):
    """Like aiohttp raise_for_status, but it distinguishes between retryable and non-retryable
    errors."""
    if not response.ok:
        if response.status >= 500 or response.status == 429:
            raise RetryableResponseError(response.status)
        else:
            text = await response.text()
            raise NonRetryableResponseError(response.status, text)


def http_default_fields() -> list[BatchExportField]:
    """Return default fields used in HTTP batch export, currently supporting only migrations."""
    return [
        BatchExportField(expression="uuid", alias="uuid"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="_inserted_at", alias="_inserted_at"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="nullIf(properties, '')", alias="properties"),
        BatchExportField(expression="distinct_id", alias="distinct_id"),
        BatchExportField(expression="elements_chain", alias="elements_chain"),
    ]


class HeartbeatDetails:
    """This class allows us to enforce a schema on the Heartbeat details.

    Attributes:
        last_uploaded_timestamp: The timestamp of the last batch we managed to upload.
    """

    last_uploaded_timestamp: str

    def __init__(self, last_uploaded_timestamp: str):
        self.last_uploaded_timestamp = last_uploaded_timestamp

    @classmethod
    def from_activity_details(cls, details) -> "HeartbeatDetails":
        last_uploaded_timestamp = details[0]
        return HeartbeatDetails(last_uploaded_timestamp)


@dataclasses.dataclass(kw_only=True)
class HttpInsertInputs(BatchExportInsertInputs):
    """Inputs for HTTP insert activity."""

    url: str
    token: str


async def maybe_resume_from_heartbeat(inputs: HttpInsertInputs) -> str | None:
    """Returns the `interval_start` to use, either resuming from previous heartbeat data or
    using the `data_interval_start` from the inputs."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="HTTP")

    interval_start = inputs.data_interval_start
    details = activity.info().heartbeat_details

    if not details:
        # No heartbeat found, so we start from the beginning.
        return interval_start

    try:
        interval_start = HeartbeatDetails.from_activity_details(details).last_uploaded_timestamp
    except IndexError:
        # This is the error we expect when there are no activity details as the sequence will be
        # empty.
        logger.debug(
            "Did not receive details from previous activity Excecution. Export will start from the beginning %s",
            interval_start,
        )
    except Exception:
        # We still start from the beginning, but we make a point to log unexpected errors. Ideally,
        # any new exceptions should be added to the previous block after the first time and we will
        # never land here.
        logger.warning(
            "Did not receive details from previous activity Excecution due to an unexpected error. Export will start from the beginning %s",
            interval_start,
        )

    return interval_start


async def post_json_file_to_url(url, batch_file, session: aiohttp.ClientSession):
    batch_file.rewind()

    headers = {"Content-Type": "application/json"}
    data_reader = io.BufferedReader(batch_file)
    # aiohttp claims file as their own and closes it.
    # Doesn't appear this is going to change, so we don't let them close us.
    # It may be worth it to explore other libraries.
    # See: https://github.com/aio-libs/aiohttp/issues/1907
    data_reader.close = lambda: None  # type: ignore

    async with session.post(url, data=data_reader, headers=headers) as response:
        await raise_for_status(response)

    data_reader.detach()
    return response


@activity.defn
async def insert_into_http_activity(inputs: HttpInsertInputs) -> RecordsCompleted:
    """Activity streams data from ClickHouse to an HTTP Endpoint."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="HTTP")
    logger.info(
        "Batch exporting range %s - %s to HTTP endpoint: %s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.url,
    )

    async with get_client(team_id=inputs.team_id) as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        if inputs.batch_export_schema is not None:
            raise NotImplementedError("Batch export schema is not supported for HTTP export")

        fields = http_default_fields()
        columns = [field["alias"] for field in fields]

        interval_start = await maybe_resume_from_heartbeat(inputs)

        is_backfill = inputs.get_is_backfill()

        record_iterator = iter_records(
            client=client,
            team_id=inputs.team_id,
            interval_start=interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=fields,
            extra_query_parameters=None,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
        )

        last_uploaded_timestamp: str | None = None

        async def worker_shutdown_handler():
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            logger.warn(
                f"Worker shutting down! Reporting back latest exported part {last_uploaded_timestamp}",
            )
            if last_uploaded_timestamp is None:
                # Don't heartbeat if worker shuts down before we could even send anything
                # Just start from the beginning again.
                return

            activity.heartbeat(last_uploaded_timestamp)

        asyncio.create_task(worker_shutdown_handler())

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        # The HTTP destination currently only supports the PostHog batch capture endpoint. In the
        # future we may support other endpoints, but we'll need a way to template the request body,
        # headers, etc.
        #
        # For now, we write the batch out in PostHog capture format, which means each Batch Export
        # temporary file starts with a header and ends with a footer.
        #
        # For example:
        #
        #   Header written when temp file is opened: {"api_key": "api-key-from-inputs","batch": [
        #   Each record is written out as an object:   {"event": "foo", ...},
        #   Finally, a footer is written out:        ]}
        #
        # Why write to a file at all? Because we need to serialize the data anyway, and it's the
        # safest way to stay within batch endpoint payload limits and not waste process memory.
        posthog_batch_header = """{{"api_key": "{}","historical_migration":true,"batch": [""".format(inputs.token)
        posthog_batch_footer = "]}"

        with BatchExportTemporaryFile() as batch_file:

            def write_event_to_batch(event):
                if batch_file.records_since_last_reset == 0:
                    batch_file.write(posthog_batch_header)
                else:
                    batch_file.write(",")

                batch_file.write_record_as_bytes(json_dumps_bytes(event))

            async def flush_batch_to_http_endpoint(last_uploaded_timestamp: str, session: aiohttp.ClientSession):
                logger.debug(
                    "Sending %s records of size %s bytes",
                    batch_file.records_since_last_reset,
                    batch_file.bytes_since_last_reset,
                )

                batch_file.write(posthog_batch_footer)

                await post_json_file_to_url(inputs.url, batch_file, session)

                rows_exported.add(batch_file.records_since_last_reset)
                bytes_exported.add(batch_file.bytes_since_last_reset)

                activity.heartbeat(last_uploaded_timestamp)

            async with aiohttp.ClientSession() as session:
                for record_batch in record_iterator:
                    for row in record_batch.select(columns).to_pylist():
                        # Format result row as PostHog event, write JSON to the batch file.

                        properties = row["properties"]
                        properties = json.loads(properties) if properties else {}
                        properties["$geoip_disable"] = True

                        if row["event"] == "$autocapture" and row["elements_chain"] is not None:
                            properties["$elements_chain"] = row["elements_chain"]

                        capture_event = {
                            "uuid": row["uuid"],
                            "distinct_id": row["distinct_id"],
                            "timestamp": row["timestamp"],
                            "event": row["event"],
                            "properties": properties,
                        }

                        inserted_at = row.pop("_inserted_at")

                        write_event_to_batch(capture_event)

                        if (
                            batch_file.tell() > settings.BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES
                            or batch_file.records_since_last_reset >= settings.BATCH_EXPORT_HTTP_BATCH_SIZE
                        ):
                            last_uploaded_timestamp = str(inserted_at)
                            await flush_batch_to_http_endpoint(last_uploaded_timestamp, session)
                            batch_file.reset()

                if batch_file.tell() > 0:
                    last_uploaded_timestamp = str(inserted_at)
                    await flush_batch_to_http_endpoint(last_uploaded_timestamp, session)

            return batch_file.records_total


@workflow.defn(name="http-export")
class HttpBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data to an HTTP endpoint.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> HttpBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return HttpBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: HttpBatchExportInputs):
        """Workflow implementation to export data to an HTTP Endpoint."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )
        run_id = await workflow.execute_activity(
            start_batch_export_run,
            start_batch_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        finish_inputs = FinishBatchExportRunInputs(
            id=run_id,
            batch_export_id=inputs.batch_export_id,
            status=BatchExportRun.Status.COMPLETED,
            team_id=inputs.team_id,
        )

        insert_inputs = HttpInsertInputs(
            team_id=inputs.team_id,
            url=inputs.url,
            token=inputs.token,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            batch_export_schema=inputs.batch_export_schema,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
        )

        await execute_batch_export_insert_activity(
            insert_into_http_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=[
                "NonRetryableResponseError",
            ],
            finish_inputs=finish_inputs,
            # Disable heartbeat timeout until we add heartbeat support.
            heartbeat_timeout_seconds=None,
        )
