import collections.abc
import csv
import dataclasses
import datetime as dt
import gzip
import json
import logging
import logging.handlers
import queue
import tempfile
import typing
import uuid
from string import Template

import brotli
from asgiref.sync import sync_to_async
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportsInputsProtocol,
    create_batch_export_backfill,
    create_batch_export_run,
    update_batch_export_backfill_status,
    update_batch_export_run_status,
)
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES

SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT $fields
    FROM events
    WHERE
        -- These 'timestamp' checks are a heuristic to exploit the sort key.
        -- Ideally, we need a schema that serves our needs, i.e. with a sort key on the _timestamp field used for batch exports.
        -- As a side-effect, this heuristic will discard historical loads older than 2 days.
        timestamp >= toDateTime64({data_interval_start}, 6, 'UTC') - INTERVAL 2 DAY
        AND timestamp < toDateTime64({data_interval_end}, 6, 'UTC') + INTERVAL 1 DAY
        AND COALESCE(inserted_at, _timestamp) >= toDateTime64({data_interval_start}, 6, 'UTC')
        AND COALESCE(inserted_at, _timestamp) < toDateTime64({data_interval_end}, 6, 'UTC')
        AND team_id = {team_id}
        $exclude_events
        $include_events
    $order_by
    $format
    """
)


async def get_rows_count(
    client,
    team_id: int,
    interval_start: str,
    interval_end: str,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
) -> int:
    data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    if exclude_events:
        exclude_events_statement = "AND event NOT IN {exclude_events}"
        events_to_exclude_tuple = tuple(exclude_events)
    else:
        exclude_events_statement = ""
        events_to_exclude_tuple = ()

    if include_events:
        include_events_statement = "AND event IN {include_events}"
        events_to_include_tuple = tuple(include_events)
    else:
        include_events_statement = ""
        events_to_include_tuple = ()

    query = SELECT_QUERY_TEMPLATE.substitute(
        fields="count(DISTINCT event, cityHash64(distinct_id), cityHash64(uuid)) as count",
        order_by="",
        format="",
        exclude_events=exclude_events_statement,
        include_events=include_events_statement,
    )

    count = await client.read_query(
        query,
        query_parameters={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
            "exclude_events": events_to_exclude_tuple,
            "include_events": events_to_include_tuple,
        },
    )

    if count is None or len(count) == 0:
        raise ValueError("Unexpected result from ClickHouse: `None` returned for count query")

    return int(count)


FIELDS = """
DISTINCT ON (event, cityHash64(distinct_id), cityHash64(uuid))
toString(uuid) as uuid,
team_id,
timestamp,
inserted_at,
created_at,
event,
properties,
-- Point in time identity fields
toString(distinct_id) as distinct_id,
toString(person_id) as person_id,
-- Autocapture fields
elements_chain
"""

S3_FIELDS = """
DISTINCT ON (event, cityHash64(distinct_id), cityHash64(uuid))
toString(uuid) as uuid,
team_id,
timestamp,
inserted_at,
created_at,
event,
properties,
-- Point in time identity fields
toString(distinct_id) as distinct_id,
toString(person_id) as person_id,
person_properties,
-- Autocapture fields
elements_chain
"""


def get_results_iterator(
    client,
    team_id: int,
    interval_start: str,
    interval_end: str,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
    include_person_properties: bool = False,
) -> typing.Generator[dict[str, typing.Any], None, None]:
    data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    if exclude_events:
        exclude_events_statement = "AND event NOT IN {exclude_events}"
        events_to_exclude_tuple = tuple(exclude_events)
    else:
        exclude_events_statement = ""
        events_to_exclude_tuple = ()

    if include_events:
        include_events_statement = "AND event IN {include_events}"
        events_to_include_tuple = tuple(include_events)
    else:
        include_events_statement = ""
        events_to_include_tuple = ()

    query = SELECT_QUERY_TEMPLATE.substitute(
        fields=S3_FIELDS if include_person_properties else FIELDS,
        order_by="ORDER BY inserted_at",
        format="FORMAT ArrowStream",
        exclude_events=exclude_events_statement,
        include_events=include_events_statement,
    )

    for batch in client.stream_query_as_arrow(
        query,
        query_parameters={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
            "exclude_events": events_to_exclude_tuple,
            "include_events": events_to_include_tuple,
        },
    ):
        yield from iter_batch_records(batch)


def iter_batch_records(batch) -> typing.Generator[dict[str, typing.Any], None, None]:
    """Iterate over records of a batch.

    During iteration, we yield dictionaries with all fields used by PostHog BatchExports.

    Args:
        batch: A record batch of rows.
    """
    for record in batch.to_pylist():
        properties = record.get("properties")
        person_properties = record.get("person_properties")
        properties = json.loads(properties) if properties else None

        # This is not backwards compatible, as elements should contain a parsed array.
        # However, parsing elements_chain is a mess, so we json.dump to at least be compatible with
        # schemas that use JSON-like types.
        elements = json.dumps(record.get("elements_chain").decode())

        record = {
            "created_at": record.get("created_at").isoformat(),
            "distinct_id": record.get("distinct_id").decode(),
            "elements": elements,
            "elements_chain": record.get("elements_chain").decode(),
            "event": record.get("event").decode(),
            "inserted_at": record.get("inserted_at").isoformat() if record.get("inserted_at") else None,
            "ip": properties.get("$ip", None) if properties else None,
            "person_id": record.get("person_id").decode(),
            "person_properties": json.loads(person_properties) if person_properties else None,
            "set": properties.get("$set", None) if properties else None,
            "set_once": properties.get("$set_once", None) if properties else None,
            "properties": properties,
            # Kept for backwards compatibility, but not exported anymore.
            "site_url": "",
            "team_id": record.get("team_id"),
            "timestamp": record.get("timestamp").isoformat(),
            "uuid": record.get("uuid").decode(),
        }

        yield record


def get_data_interval(interval: str, data_interval_end: str | None) -> tuple[dt.datetime, dt.datetime]:
    """Return the start and end of an export's data interval.

    Args:
        interval: The interval of the BatchExport associated with this Workflow.
        data_interval_end: The optional end of the BatchExport period. If not included, we will
            attempt to extract it from Temporal SearchAttributes.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.
        ValueError: If passing an unsupported interval value.

    Returns:
        A tuple of two dt.datetime indicating start and end of the data_interval.
    """
    data_interval_end_str = data_interval_end

    if not data_interval_end_str:
        data_interval_end_search_attr = workflow.info().search_attributes.get("TemporalScheduledStartTime")

        # These two if-checks are a bit pedantic, but Temporal SDK is heavily typed.
        # So, they exist to make mypy happy.
        if data_interval_end_search_attr is None:
            msg = (
                "Expected 'TemporalScheduledStartTime' of type 'list[str]' or 'list[datetime], found 'NoneType'."
                "This should be set by the Temporal Schedule unless triggering workflow manually."
                "In the latter case, ensure 'S3BatchExportInputs.data_interval_end' is set."
            )
            raise TypeError(msg)

        # Failing here would perhaps be a bug in Temporal.
        if isinstance(data_interval_end_search_attr[0], str):
            data_interval_end_str = data_interval_end_search_attr[0]
            data_interval_end_dt = dt.datetime.fromisoformat(data_interval_end_str)

        elif isinstance(data_interval_end_search_attr[0], dt.datetime):
            data_interval_end_dt = data_interval_end_search_attr[0]

        else:
            msg = (
                f"Expected search attribute to be of type 'str' or 'datetime' found '{data_interval_end_search_attr[0]}' "
                f"of type '{type(data_interval_end_search_attr[0])}'."
            )
            raise TypeError(msg)
    else:
        data_interval_end_dt = dt.datetime.fromisoformat(data_interval_end_str)

    if interval == "hour":
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(hours=1)
    elif interval == "day":
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(days=1)
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(**kwargs)
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

    return (data_interval_start_dt, data_interval_end_dt)


def json_dumps_bytes(d, encoding="utf-8") -> bytes:
    return json.dumps(d).encode(encoding)


class BatchExportTemporaryFile:
    """A TemporaryFile used to as an intermediate step while exporting data.

    This class does not implement the file-like interface but rather passes any calls
    to the underlying tempfile.NamedTemporaryFile. We do override 'write' methods
    to allow tracking bytes and records.
    """

    def __init__(
        self,
        mode: str = "w+b",
        buffering=-1,
        compression: str | None = None,
        encoding: str | None = None,
        newline: str | None = None,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        *,
        errors: str | None = None,
    ):
        self._file = tempfile.NamedTemporaryFile(
            mode=mode,
            encoding=encoding,
            newline=newline,
            buffering=buffering,
            suffix=suffix,
            prefix=prefix,
            dir=dir,
            errors=errors,
        )
        self.compression = compression
        self.bytes_total = 0
        self.records_total = 0
        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0
        self._brotli_compressor = None

    def __getattr__(self, name):
        """Pass get attr to underlying tempfile.NamedTemporaryFile."""
        return self._file.__getattr__(name)

    def __enter__(self):
        """Context-manager protocol enter method."""
        self._file.__enter__()
        return self

    def __exit__(self, exc, value, tb):
        """Context-manager protocol exit method."""
        return self._file.__exit__(exc, value, tb)

    def __iter__(self):
        yield from self._file

    @property
    def brotli_compressor(self):
        if self._brotli_compressor is None:
            self._brotli_compressor = brotli.Compressor()
        return self._brotli_compressor

    def compress(self, content: bytes | str) -> bytes:
        if isinstance(content, str):
            encoded = content.encode("utf-8")
        else:
            encoded = content

        match self.compression:
            case "gzip":
                return gzip.compress(encoded)
            case "brotli":
                self.brotli_compressor.process(encoded)
                return self.brotli_compressor.flush()
            case None:
                return encoded
            case _:
                raise ValueError(f"Unsupported compression: '{self.compression}'")

    def write(self, content: bytes | str):
        """Write bytes to underlying file keeping track of how many bytes were written."""
        compressed_content = self.compress(content)

        if "b" in self.mode:
            result = self._file.write(compressed_content)
        else:
            result = self._file.write(compressed_content.decode("utf-8"))

        self.bytes_total += result
        self.bytes_since_last_reset += result

        return result

    def write_records_to_jsonl(self, records):
        """Write records to a temporary file as JSONL."""
        jsonl_dump = b"\n".join(map(json_dumps_bytes, records))

        if len(records) == 1:
            jsonl_dump += b"\n"

        result = self.write(jsonl_dump)

        self.records_total += len(records)
        self.records_since_last_reset += len(records)

        return result

    def write_records_to_csv(
        self,
        records,
        fieldnames: None | collections.abc.Sequence[str] = None,
        extrasaction: typing.Literal["raise", "ignore"] = "ignore",
        delimiter: str = ",",
        quotechar: str = '"',
        escapechar: str = "\\",
        quoting=csv.QUOTE_NONE,
    ):
        """Write records to a temporary file as CSV."""
        if len(records) == 0:
            return

        if fieldnames is None:
            fieldnames = list(records[0].keys())

        writer = csv.DictWriter(
            self,
            fieldnames=fieldnames,
            extrasaction=extrasaction,
            delimiter=delimiter,
            quotechar=quotechar,
            escapechar=escapechar,
            quoting=quoting,
        )
        writer.writerows(records)

        self.records_total += len(records)
        self.records_since_last_reset += len(records)

    def write_records_to_tsv(
        self,
        records,
        fieldnames: None | list[str] = None,
        extrasaction: typing.Literal["raise", "ignore"] = "ignore",
        quotechar: str = '"',
        escapechar: str = "\\",
        quoting=csv.QUOTE_NONE,
    ):
        """Write records to a temporary file as TSV."""
        return self.write_records_to_csv(
            records,
            fieldnames=fieldnames,
            extrasaction=extrasaction,
            delimiter="\t",
            quotechar=quotechar,
            escapechar=escapechar,
            quoting=quoting,
        )

    def rewind(self):
        """Rewind the file before reading it."""
        if self.compression == "brotli":
            result = self._file.write(self.brotli_compressor.finish())

            self.bytes_total += result
            self.bytes_since_last_reset += result

            self._brotli_compressor = None

        self._file.seek(0)

    def reset(self):
        """Reset underlying file by truncating it.

        Also resets the tracker attributes for bytes and records since last reset.
        """
        self._file.seek(0)
        self._file.truncate()

        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0


class BatchExportLoggerAdapter(logging.LoggerAdapter):
    """Adapter that adds batch export details to log records."""

    def __init__(
        self,
        logger: logging.Logger,
        extra=None,
    ) -> None:
        """Create the logger adapter."""
        super().__init__(logger, extra or {})

    def process(self, msg: str, kwargs) -> tuple[typing.Any, collections.abc.MutableMapping[str, typing.Any]]:
        """Override to add batch exports details."""
        workflow_id = None
        workflow_run_id = None
        attempt = None

        try:
            activity_info = activity.info()
        except RuntimeError:
            pass
        else:
            workflow_run_id = activity_info.workflow_run_id
            workflow_id = activity_info.workflow_id
            attempt = activity_info.attempt

        try:
            workflow_info = workflow.info()
        except RuntimeError:
            pass
        else:
            workflow_run_id = workflow_info.run_id
            workflow_id = workflow_info.workflow_id
            attempt = workflow_info.attempt

        if workflow_id is None or workflow_run_id is None or attempt is None:
            return (None, {})

        # This works because the WorkflowID is made up like f"{batch_export_id}-{data_interval_end}"
        # Since {data_interval_date} is an iso formatted datetime string, it has two '-' to separate the
        # date. Plus one more leaves us at the end of {batch_export_id}.
        batch_export_id = workflow_id.rsplit("-", maxsplit=3)[0]

        extra = kwargs.get("extra", None) or {}
        extra["workflow_id"] = workflow_id
        extra["batch_export_id"] = batch_export_id
        extra["workflow_run_id"] = workflow_run_id
        extra["attempt"] = attempt

        if isinstance(self.extra, dict):
            extra = extra | self.extra
        kwargs["extra"] = extra

        return (msg, kwargs)

    @property
    def base_logger(self) -> logging.Logger:
        """Underlying logger usable for actions such as adding handlers/formatters."""
        return self.logger


class BatchExportsLogRecord(logging.LogRecord):
    team_id: int
    batch_export_id: str
    workflow_run_id: str
    attempt: int


class KafkaLoggingHandler(logging.Handler):
    def __init__(self, topic, key=None):
        super().__init__()
        self.producer = KafkaProducer()
        self.topic = topic
        self.key = key

    def emit(self, record):
        if record.name == "kafka":
            return

        # This is a lie, but as long as this handler is used together
        # with BatchExportLoggerAdapter we should be fine.
        # This is definitely cheaper than a bunch if checks for attributes.
        record = typing.cast(BatchExportsLogRecord, record)

        msg = self.format(record)
        data = {
            "instance_id": record.workflow_run_id,
            "level": record.levelname,
            "log_source": "batch_exports",
            "log_source_id": record.batch_export_id,
            "message": msg,
            "team_id": record.team_id,
            "timestamp": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        try:
            future = self.producer.produce(topic=self.topic, data=data, key=self.key)
            future.get(timeout=1)
        except Exception as e:
            logging.exception("Failed to produce log to Kafka topic %s", self.topic, exc_info=e)

    def close(self):
        self.producer.close()
        logging.Handler.close(self)


LOG_QUEUE: queue.Queue = queue.Queue(-1)
QUEUE_HANDLER = logging.handlers.QueueHandler(LOG_QUEUE)
QUEUE_HANDLER.setLevel(logging.DEBUG)

KAFKA_HANDLER = KafkaLoggingHandler(topic=KAFKA_LOG_ENTRIES)
KAFKA_HANDLER.setLevel(logging.DEBUG)
QUEUE_LISTENER = logging.handlers.QueueListener(LOG_QUEUE, KAFKA_HANDLER)

logger = logging.getLogger(__name__)
logger.addHandler(QUEUE_HANDLER)
logger.setLevel(logging.DEBUG)


def get_batch_exports_logger(inputs: BatchExportsInputsProtocol) -> BatchExportLoggerAdapter:
    """Return a logger for BatchExports."""
    # Need a type comment as _thread is private.
    if QUEUE_LISTENER._thread is None:  # type: ignore
        QUEUE_LISTENER.start()

    adapter = BatchExportLoggerAdapter(logger, {"team_id": inputs.team_id})

    return adapter


@dataclasses.dataclass
class CreateBatchExportRunInputs:
    """Inputs to the create_export_run activity.

    Attributes:
        team_id: The id of the team the BatchExportRun belongs to.
        batch_export_id: The id of the BatchExport this BatchExportRun belongs to.
        data_interval_start: Start of this BatchExportRun's data interval.
        data_interval_end: End of this BatchExportRun's data interval.
    """

    team_id: int
    batch_export_id: str
    data_interval_start: str
    data_interval_end: str
    status: str = "Starting"


@activity.defn
async def create_export_run(inputs: CreateBatchExportRunInputs) -> str:
    """Activity that creates an BatchExportRun.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.
    """
    logger = get_batch_exports_logger(inputs=inputs)
    logger.info(f"Creating BatchExportRun model instance in team {inputs.team_id}.")

    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(create_batch_export_run)(  # type: ignore
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=inputs.status,
    )

    logger.info(f"Created BatchExportRun {run.id} in team {inputs.team_id}.")

    return str(run.id)


@dataclasses.dataclass
class UpdateBatchExportRunStatusInputs:
    """Inputs to the update_export_run_status activity."""

    id: str
    status: str
    latest_error: str | None = None


@activity.defn
async def update_export_run_status(inputs: UpdateBatchExportRunStatusInputs):
    """Activity that updates the status of an BatchExportRun."""
    await sync_to_async(update_batch_export_run_status)(
        run_id=uuid.UUID(inputs.id),
        status=inputs.status,
        latest_error=inputs.latest_error,
    )  # type: ignore


@dataclasses.dataclass
class CreateBatchExportBackfillInputs:
    team_id: int
    batch_export_id: str
    start_at: str
    end_at: str
    status: str


@activity.defn
async def create_batch_export_backfill_model(inputs: CreateBatchExportBackfillInputs) -> str:
    """Activity that creates an BatchExportBackfill.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.
    """
    logger = get_batch_exports_logger(inputs=inputs)
    logger.info(f"Creating BatchExportBackfill model instance in team {inputs.team_id}.")

    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(create_batch_export_backfill)(  # type: ignore
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        start_at=inputs.start_at,
        end_at=inputs.end_at,
        status=inputs.status,
        team_id=inputs.team_id,
    )

    logger.info(f"Created BatchExportBackfill {run.id} in team {inputs.team_id}.")

    return str(run.id)


@dataclasses.dataclass
class UpdateBatchExportBackfillStatusInputs:
    """Inputs to the update_batch_export_backfill_status activity."""

    id: str
    status: str


@activity.defn
async def update_batch_export_backfill_model_status(inputs: UpdateBatchExportBackfillStatusInputs):
    """Activity that updates the status of an BatchExportRun."""
    await sync_to_async(update_batch_export_backfill_status)(backfill_id=uuid.UUID(inputs.id), status=inputs.status)  # type: ignore


async def execute_batch_export_insert_activity(
    activity,
    inputs,
    non_retryable_error_types: list[str],
    update_inputs: UpdateBatchExportRunStatusInputs,
    start_to_close_timeout_seconds: int = 3600,
    heartbeat_timeout_seconds: int = 120,
    maximum_attempts: int = 10,
    initial_retry_interval_seconds: int = 10,
    maximum_retry_interval_seconds: int = 120,
) -> None:
    """Execute the main insert activity of a batch export handling any errors.

    All batch exports boil down to inserting some data somewhere, and they all follow the same error
    handling patterns: logging and updating run status. For this reason, we have this function
    to abstract executing the main insert activity of each batch export.

    Args:
        activity: The 'insert_into_*' activity function to execute.
        inputs: The inputs to the activity.
        non_retryable_error_types: A list of errors to not retry on when executing the activity.
        update_inputs: Inputs to the update_export_run_status to run at the end.
        start_to_close_timeout: A timeout for the 'insert_into_*' activity function.
        maximum_attempts: Maximum number of retries for the 'insert_into_*' activity function.
            Assuming the error that triggered the retry is not in non_retryable_error_types.
        initial_retry_interval_seconds: When retrying, seconds until the first retry.
        maximum_retry_interval_seconds: Maximum interval in seconds between retries.
    """
    logger = get_batch_exports_logger(inputs=inputs)

    retry_policy = RetryPolicy(
        initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
        maximum_interval=dt.timedelta(seconds=maximum_retry_interval_seconds),
        maximum_attempts=maximum_attempts,
        non_retryable_error_types=non_retryable_error_types,
    )
    try:
        await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=start_to_close_timeout_seconds),
            heartbeat_timeout=dt.timedelta(seconds=heartbeat_timeout_seconds),
            retry_policy=retry_policy,
        )
    except exceptions.ActivityError as e:
        if isinstance(e.cause, exceptions.CancelledError):
            logger.error("BatchExport was cancelled.")
            update_inputs.status = "Cancelled"
        else:
            logger.exception("BatchExport failed.", exc_info=e.cause)
            update_inputs.status = "Failed"

        update_inputs.latest_error = str(e.cause)
        raise

    except Exception as e:
        logger.exception("BatchExport failed with an unexpected error.", exc_info=e)
        update_inputs.status = "Failed"
        update_inputs.latest_error = "An unexpected error has ocurred"
        raise

    else:
        logger.info(
            "Successfully finished exporting batch %s - %s", inputs.data_interval_start, inputs.data_interval_end
        )

    finally:
        await workflow.execute_activity(
            update_export_run_status,
            update_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )
