import aiohttp
import datetime as dt
import json
from dataclasses import dataclass

from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BatchExportField, BatchExportSchema, HttpBatchExportInputs
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    BatchExportTemporaryFile,
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    execute_batch_export_insert_activity,
    get_data_interval,
    get_rows_count,
    iter_records,
    json_dumps_bytes,
)
from posthog.temporal.batch_exports.clickhouse import get_client
from posthog.temporal.batch_exports.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger


class RetryableResponseError(Exception):
    """Error for HTTP status >=500 (plus 429)."""

    def __init__(self, status):
        super().__init__(f"RetryableResponseError status: {status}")


class NonRetryableResponseError(Exception):
    """Error for HTTP status >= 400 and < 500 (excluding 429)."""

    def __init__(self, status):
        super().__init__(f"NonRetryableResponseError status: {status}")


def raise_for_status(response: aiohttp.ClientResponse):
    """Like aiohttp raise_for_status, but it distinguishes between retryable and non-retryable
    errors."""
    if not response.ok:
        if response.status >= 500 or response.status == 429:
            raise RetryableResponseError(response.status)
        else:
            raise NonRetryableResponseError(response.status)


def http_default_fields() -> list[BatchExportField]:
    return [
        BatchExportField(expression="toString(uuid)", alias="uuid"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="nullIf(properties, '')", alias="properties"),
        BatchExportField(expression="toString(distinct_id)", alias="distinct_id"),
        BatchExportField(expression="elements_chain", alias="elements_chain"),
    ]


@dataclass
class HttpInsertInputs:
    """Inputs for HTTP insert activity."""

    team_id: int
    url: str
    token: str
    data_interval_start: str
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    batch_export_schema: BatchExportSchema | None = None


async def post_json_file_to_url(url, batch_file):
    batch_file.seek(0)
    async with aiohttp.ClientSession() as session:
        headers = {"Content-Type": "application/json"}
        async with session.post(url, data=batch_file, headers=headers) as response:
            raise_for_status(response)
            return response


@activity.defn
async def insert_into_http_activity(inputs: HttpInsertInputs):
    """Activity streams data from ClickHouse to an HTTP Endpoint."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="HTTP")
    logger.info(
        "Exporting batch %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

        if count == 0:
            logger.info(
                "Nothing to export in batch %s - %s",
                inputs.data_interval_start,
                inputs.data_interval_end,
            )
            return

        logger.info("BatchExporting %s rows", count)

        if inputs.batch_export_schema is not None:
            raise NotImplementedError("Batch export schema is not supported for HTTP export")

        fields = http_default_fields()
        columns = [field["alias"] for field in fields]

        record_iterator = iter_records(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=fields,
            extra_query_parameters=None,
        )

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
        posthog_batch_header = """{"api_key": "%s","batch": [""" % inputs.token
        posthog_batch_footer = "]}"

        with BatchExportTemporaryFile() as batch_file:

            def write_event_to_batch(event):
                if batch_file.records_since_last_reset == 0:
                    batch_file.write(posthog_batch_header)
                else:
                    batch_file.write(",")

                batch_file.write_record_as_bytes(json_dumps_bytes(event))

            async def flush_batch():
                logger.debug(
                    "Sending %s records of size %s bytes",
                    batch_file.records_since_last_reset,
                    batch_file.bytes_since_last_reset,
                )

                batch_file.write(posthog_batch_footer)
                await post_json_file_to_url(inputs.url, batch_file)

                rows_exported.add(batch_file.records_since_last_reset)
                bytes_exported.add(batch_file.bytes_since_last_reset)

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

                    write_event_to_batch(capture_event)

                    if (
                        batch_file.tell() > settings.BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES
                        or batch_file.records_since_last_reset >= settings.BATCH_EXPORT_HTTP_BATCH_SIZE
                    ):
                        await flush_batch()
                        batch_file.reset()

            if batch_file.tell() > 0:
                await flush_batch()


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
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)

        create_export_run_inputs = CreateBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=[
                    "NonRetryableResponseError",
                ],
            ),
        )

        update_inputs = UpdateBatchExportRunStatusInputs(
            id=run_id,
            status="Completed",
            team_id=inputs.team_id,
        )

        insert_inputs = HttpInsertInputs(
            team_id=inputs.team_id,
            url=inputs.url,
            token=inputs.token,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_http_activity,
            insert_inputs,
            non_retryable_error_types=[
                "NonRetryableResponseError",
            ],
            update_inputs=update_inputs,
            # Disable heartbeat timeout until we add heartbeat support.
            heartbeat_timeout_seconds=None,
        )
