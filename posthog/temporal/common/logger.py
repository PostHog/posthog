import asyncio
import json
import logging
import queue as sync_queue
import ssl
import threading
import uuid
from contextvars import copy_context

import aiokafka
import structlog
import temporalio.activity
from django.conf import settings
from kafka import KafkaProducer
from structlog.processors import EventRenamer
from structlog.typing import FilteringBoundLogger

from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES

BACKGROUND_LOGGER_TASKS = set()


def get_internal_logger():
    """Return a logger for internal use, where logs do not get sent to Kafka.

    We attach the temporal context to the logger for easier debugging (for
    example, we can track things like the workflow id across log entries).
    """
    logger = structlog.get_logger()
    temporal_context = get_temporal_context()

    return logger.new(**temporal_context)


async def bind_temporal_worker_logger(team_id: int, destination: str | None = None) -> FilteringBoundLogger:
    """Return a bound logger for Temporal Workers."""
    if not structlog.is_configured():
        configure_logger_async()

    logger = structlog.get_logger()
    temporal_context = get_temporal_context()

    return logger.new(team_id=team_id, destination=destination, **temporal_context)


def bind_temporal_worker_logger_sync(team_id: int, destination: str | None = None) -> FilteringBoundLogger:
    """Return a bound logger for Temporal Workers."""
    if not structlog.is_configured():
        configure_logger_sync()

    logger = structlog.get_logger()
    temporal_context = get_temporal_context()

    return logger.new(team_id=team_id, destination=destination, **temporal_context)


async def configure_temporal_worker_logger(
    logger, team_id: int, destination: str | None = None
) -> FilteringBoundLogger:
    """Return a bound logger for Temporal Workers."""
    if not structlog.is_configured():
        configure_logger_async()

    temporal_context = get_temporal_context()

    return logger.new(team_id=team_id, destination=destination, **temporal_context)


async def bind_temporal_org_worker_logger(
    organization_id: uuid.UUID, destination: str | None = None
) -> FilteringBoundLogger:
    """Return a bound logger for Temporal Workers scoped by organization instead of team."""
    if not structlog.is_configured():
        configure_logger_async()

    logger = structlog.get_logger()
    temporal_context = get_temporal_context()

    return logger.new(organization_id=str(organization_id), destination=destination, **temporal_context)


def configure_logger_sync(
    logger_factory=structlog.PrintLoggerFactory,
    extra_processors: list[structlog.types.Processor] | None = None,
    queue: sync_queue.Queue | None = None,
    producer: KafkaProducer | None = None,
    cache_logger_on_first_use: bool = True,
) -> None:
    """Configure a sync StructLog logger for temporal workflows.

    Keep up to date with the async version `configure_logger_async`

    Configuring the logger involves:
    * Setting up processors.
    * Spawning a task to listen for Kafka logs.
    * Spawning a task to shutdown gracefully on worker shutdown.

    Args:
        logger_factory: Optionally, override the logger_factory.
        extra_processors: Optionally, add any processors at the end of the chain.
        queue: Optionally, bring your own log queue.
        producer: Optionally, bring your own Kafka producer.
        cache_logger_on_first_use: Set whether to cache logger for performance.
            Should always be True except in tests.
    """

    base_processors: list[structlog.types.Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]

    log_queue = queue if queue is not None else sync_queue.Queue(maxsize=-1)
    log_producer = None
    log_producer_error = None

    try:
        log_producer = KafkaLogProducerFromQueueSync(queue=log_queue, topic=KAFKA_LOG_ENTRIES, producer=producer)
    except Exception as e:
        # Skip putting logs in queue if we don't have a producer that can consume the queue.
        # We save the error to log it later as the logger hasn't yet been configured at this time.
        log_producer_error = e
    else:
        put_in_queue = PutInLogQueueProcessor(log_queue)
        base_processors.append(put_in_queue)

    base_processors += [
        EventRenamer("msg"),
        structlog.processors.JSONRenderer(),
    ]
    extra_processors_to_add = extra_processors if extra_processors is not None else []

    structlog.configure(
        processors=base_processors + extra_processors_to_add,
        logger_factory=logger_factory(),
        cache_logger_on_first_use=cache_logger_on_first_use,
    )

    if log_producer is None:
        logger = structlog.get_logger()
        logger.error("Failed to initialize log producer", exc_info=log_producer_error)
        return

    listener_thread = threading.Thread(target=log_producer.listen, daemon=True)
    listener_thread.start()

    def worker_shutdown_handler():
        if not temporalio.activity.in_activity():
            return

        temporalio.activity.wait_for_worker_shutdown_sync()
        log_queue.join()
        log_queue.put(None)
        listener_thread.join()

    context = copy_context()
    shutdown_thread = threading.Thread(target=context.run, args=(worker_shutdown_handler,), daemon=True)
    shutdown_thread.start()


def configure_logger_async(
    logger_factory=structlog.PrintLoggerFactory,
    extra_processors: list[structlog.types.Processor] | None = None,
    queue: asyncio.Queue | None = None,
    producer: aiokafka.AIOKafkaProducer | None = None,
    cache_logger_on_first_use: bool = True,
) -> None:
    """Configure a StructLog logger for temporal workflows.

    Keep up to date with the sync version `configure_logger_sync`

    Configuring the logger involves:
    * Setting up processors.
    * Spawning a task to listen for Kafka logs.
    * Spawning a task to shutdown gracefully on worker shutdown.

    Args:
        logger_factory: Optionally, override the logger_factory.
        extra_processors: Optionally, add any processors at the end of the chain.
        queue: Optionally, bring your own log queue.
        producer: Optionally, bring your own Kafka producer.
        cache_logger_on_first_use: Set whether to cache logger for performance.
            Should always be True except in tests.
    """
    base_processors: list[structlog.types.Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]

    log_queue = queue if queue is not None else asyncio.Queue(maxsize=-1)
    log_producer = None
    log_producer_error = None

    try:
        log_producer = KafkaLogProducerFromQueueAsync(queue=log_queue, topic=KAFKA_LOG_ENTRIES, producer=producer)
    except Exception as e:
        # Skip putting logs in queue if we don't have a producer that can consume the queue.
        # We save the error to log it later as the logger hasn't yet been configured at this time.
        log_producer_error = e
    else:
        put_in_queue = PutInLogQueueProcessor(log_queue)
        base_processors.append(put_in_queue)

    base_processors += [
        EventRenamer("msg"),
        structlog.processors.JSONRenderer(),
    ]
    extra_processors_to_add = extra_processors if extra_processors is not None else []

    structlog.configure(
        processors=base_processors + extra_processors_to_add,
        logger_factory=logger_factory(),
        cache_logger_on_first_use=cache_logger_on_first_use,
    )

    if log_producer is None:
        logger = structlog.get_logger()
        logger.error("Failed to initialize log producer", exc_info=log_producer_error)
        return

    listen_task = create_logger_background_task(log_producer.listen())

    async def worker_shutdown_handler():
        """Gracefully handle a Temporal Worker shutting down.

        Graceful handling means:
        * Waiting until the queue is fully processed to avoid missing log messages.
        * Cancel task listening on queue.
        """
        await temporalio.activity.wait_for_worker_shutdown()

        listen_task.cancel()

        await asyncio.wait([listen_task])

    create_logger_background_task(worker_shutdown_handler())


def create_logger_background_task(task) -> asyncio.Task:
    """Create an asyncio.Task and add them to BACKGROUND_LOGGER_TASKS.

    Adding them to BACKGROUND_LOGGER_TASKS keeps a strong reference to the task, so they won't
    be garbage collected and disappear mid execution.
    """
    new_task = asyncio.create_task(task)
    BACKGROUND_LOGGER_TASKS.add(new_task)
    new_task.add_done_callback(BACKGROUND_LOGGER_TASKS.discard)

    return new_task


class PutInLogQueueProcessor:
    """A StructLog processor that puts event_dict into a queue.

    We format event_dict as a message to be sent to Kafka by a queue listener.
    """

    def __init__(self, queue: asyncio.Queue | sync_queue.Queue):
        self.queue = queue

    def __call__(
        self, logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
    ) -> structlog.types.EventDict:
        """Put a message into the queue, if we have all the necessary details.

        Always return event_dict so that processors that come later in the chain can do
        their own thing.
        """
        try:
            message_dict = {
                "instance_id": event_dict["workflow_run_id"],
                "level": event_dict["level"],
                "log_source": event_dict["log_source"],
                "log_source_id": event_dict["log_source_id"],
                "message": event_dict["event"],
                "team_id": event_dict["team_id"],
                "timestamp": event_dict["timestamp"],
            }
        except KeyError:
            # We don't have the required keys to ingest this log.
            # This could be because we are running outside an Activity/Workflow context.
            return event_dict

        self.queue.put_nowait(json.dumps(message_dict).encode("utf-8"))

        return event_dict


def get_temporal_context() -> dict[str, str | int]:
    """Return context variables from Temporal.

    More specifically, the context variables coming from Temporal are:
    * attempt: The current attempt number of the Temporal Workflow.
    * log_source: Either "batch_exports" or "batch_exports_backfill" or "external_data_jobs".
    * log_source_id: The batch export ID or external data source id.
    * workflow_id: The ID of the Temporal Workflow running job.
    * workflow_run_id: The ID of the Temporal Workflow Execution running the workflow.
    * workflow_type: The name of the Temporal Workflow.

    We attempt to fetch the context from the activity information. If undefined, an empty dict
    is returned. When running this in an activity the context will be defined.
    """
    activity_info = attempt_to_fetch_activity_info()

    info = activity_info

    if info is None:
        return {}

    workflow_id, workflow_type, workflow_run_id, attempt = info

    if workflow_type == "backfill-batch-export":
        # This works because the WorkflowID is made up like f"{batch_export_id}-Backfill-{data_interval_end}"
        log_source_id = workflow_id.split("-Backfill")[0]
        log_source = "batch_exports_backfill"
    elif workflow_type == "external-data-job":
        # This works because the WorkflowID is made up like f"{external_data_schema_id}-{data_interval_end}"
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "external_data_jobs"
    elif workflow_type == "deltalake-compaction-job":
        # This works because the WorkflowID is made up like f"{external_data_schema_id}-compaction"
        log_source_id = workflow_id.split("-compaction")[0]
        log_source = "deltalake_compaction_job"
    elif workflow_type == "data-modeling-run":
        # This works because the WorkflowID is made up like f"{saved_query_id}-{data_interval_end}"
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "data_modeling_run"
    else:
        # This works because the WorkflowID is made up like f"{batch_export_id}-{data_interval_end}"
        # Since 'data_interval_end' is an iso formatted datetime string, it has two '-' to separate the
        # date. Plus one more leaves us at the end of right at the end of 'batch_export_id'.
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "batch_exports"

    return {
        "attempt": attempt,
        "log_source": log_source,
        "log_source_id": log_source_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "workflow_type": workflow_type,
    }


Info = tuple[str, str, str, int]


def attempt_to_fetch_activity_info() -> Info | None:
    """Fetch Activity information from Temporal.

    Returns:
        None if calling outside an Activity, else the relevant Info.
    """
    try:
        activity_info = temporalio.activity.info()
    except RuntimeError:
        return None
    else:
        workflow_id = activity_info.workflow_id
        workflow_type = activity_info.workflow_type
        workflow_run_id = activity_info.workflow_run_id
        attempt = activity_info.attempt

    return (workflow_id, workflow_type, workflow_run_id, attempt)


class KafkaLogProducerFromQueueAsync:
    """Produce log messages to Kafka by getting them from a queue.

    This KafkaLogProducerFromQueueAsync was designed to ingest logs into the ClickHouse log_entries table.
    For this reason, the messages we produce to Kafka are serialized as JSON in the schema expected by
    the log_entries table. Eventually, we could de-couple this producer from the table schema, but
    schema changes are rare in ClickHouse, and for now we are only using this for logs, so the tight
    coupling is preferred over the extra complexity of de-coupling this producer.

    Attributes:
        queue: The queue we are listening to get log event_dicts to serialize and produce.
        topic: The topic to produce to. This should be left to the default KAFKA_LOG_ENTRIES.
        key: The key for Kafka partitioning. Default to None for random partition.
        producer: Optionally, bring your own aiokafka.AIOKafkaProducer. This is mostly here for testing.
    """

    def __init__(
        self,
        queue: asyncio.Queue,
        topic: str = KAFKA_LOG_ENTRIES,
        key: str | None = None,
        producer: aiokafka.AIOKafkaProducer | None = None,
    ):
        self.queue = queue
        self.topic = topic
        self.key = key
        self.producer = (
            producer
            if producer is not None
            else aiokafka.AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_HOSTS,
                security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
                acks="all",
                api_version="2.5.0",
                ssl_context=configure_default_ssl_context() if settings.KAFKA_SECURITY_PROTOCOL == "SSL" else None,
            )
        )
        self.logger = structlog.get_logger()

    async def listen(self):
        """Listen to messages in queue and produce them to Kafka as they come.

        This is designed to be ran as an asyncio.Task, as it will wait forever for the queue
        to have messages.
        """
        await self.producer.start()
        try:
            while True:
                msg = await self.queue.get()
                await self.produce(msg)

        finally:
            await self.flush()
            await self.producer.stop()

    async def produce(self, msg: bytes):
        """Produce messages to configured topic and key.

        We catch any exceptions so as to continue processing the queue even if the broker is unavailable
        or we fail to produce for whatever other reason. We log the failure to not fail silently.
        """
        fut = await self.producer.send(self.topic, msg, key=self.key)
        fut.add_done_callback(self.mark_queue_done)

        try:
            await fut
        except Exception:
            await self.logger.aexception("Failed to produce log to Kafka topic %s", self.topic)
            await self.logger.adebug("Message that couldn't be produced: %s", msg)

    async def flush(self):
        try:
            await self.producer.flush()
        except Exception:
            await self.logger.aexception("Failed to flush producer")

    def mark_queue_done(self, _=None):
        self.queue.task_done()


class KafkaLogProducerFromQueueSync:
    """Produce log messages to Kafka by getting them from a queue."""

    def __init__(self, queue: sync_queue.Queue, topic: str = KAFKA_LOG_ENTRIES, key: str | None = None, producer=None):
        self.queue = queue
        self.topic = topic
        self.key = key
        self.producer = producer or KafkaProducer(
            bootstrap_servers=settings.KAFKA_HOSTS,
            security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
            acks="all",
            api_version=(2, 5, 0),
            ssl_context=configure_default_ssl_context() if settings.KAFKA_SECURITY_PROTOCOL == "SSL" else None,
        )
        self.logger = structlog.get_logger()

    def listen(self):
        """Listen to messages in the queue and produce them to Kafka."""
        try:
            while True:
                msg = self.queue.get()
                if msg is None:  # Stop signal
                    break
                self.produce(msg)
        finally:
            self.flush()

    def produce(self, msg: bytes):
        """Produce messages to configured topic and key."""
        try:
            self.producer.send(self.topic, value=msg, key=self.key.encode("utf-8") if self.key else None).get(
                timeout=10
            )
        except Exception as e:
            self.logger.exception(f"Failed to produce log to Kafka topic {self.topic}: {e}")

    def flush(self):
        """Flush any remaining messages."""
        try:
            self.producer.flush()
        except Exception as e:
            self.logger.exception(f"Failed to flush producer: {e}")


def configure_default_ssl_context():
    """Setup a default SSL context for Kafka."""
    context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.verify_mode = ssl.CERT_OPTIONAL
    context.load_default_certs()
    return context
