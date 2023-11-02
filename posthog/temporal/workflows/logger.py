import asyncio
import json
import logging

import aiokafka
import structlog
import temporalio.activity
import temporalio.workflow
from django.conf import settings

from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES


async def bind_batch_exports_logger(
    team_id: int, destination: str | None = None
) -> structlog.types.FilteringBoundLogger:
    """Return a bound logger for BatchExports."""
    if not structlog.is_configured():
        await configure_logger()

    logger = structlog.get_logger()

    return logger.new(team_id=team_id, destination=destination)


async def configure_logger(
    logger_factory=structlog.PrintLoggerFactory,
    extra_processors: list[structlog.types.Processor] | None = None,
    queue: asyncio.Queue | None = None,
    producer: aiokafka.AIOKafkaProducer | None = None,
    cache_logger_on_first_use: bool = True,
) -> tuple:
    """Configure a StructLog logger for batch exports.

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
    log_queue = queue if queue is not None else asyncio.Queue(maxsize=-1)
    put_in_queue = PutInBatchExportsLogQueueProcessor(log_queue)

    base_processors: list[structlog.types.Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
        add_batch_export_context,
        put_in_queue,
        structlog.processors.EventRenamer("msg"),
        structlog.processors.JSONRenderer(),
    ]
    extra_processors_to_add = extra_processors if extra_processors is not None else []

    structlog.configure(
        processors=base_processors + extra_processors_to_add,
        logger_factory=logger_factory(),
        cache_logger_on_first_use=cache_logger_on_first_use,
    )
    listen_task = asyncio.create_task(
        KafkaLogProducerFromQueue(queue=log_queue, topic=KAFKA_LOG_ENTRIES, producer=producer).listen_and_produce()
    )

    async def worker_shutdown_handler():
        """Gracefully handle a Temporal Worker shutting down.

        Graceful handling means:
        * Waiting until the queue is fully processed to avoid missing log messages.
        * Cancel task listening on queue.
        """
        await temporalio.activity.wait_for_worker_shutdown()

        listen_task.cancel()

        await asyncio.wait([listen_task])

    worker_shutdown_handler_task = asyncio.create_task(worker_shutdown_handler())

    return (listen_task, worker_shutdown_handler_task)


class PutInBatchExportsLogQueueProcessor:
    """A StructLog processor that puts event_dict into a queue.

    We format event_dict as a message to be sent to Kafka by a queue listener.
    """

    def __init__(self, queue: asyncio.Queue):
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


def add_batch_export_context(logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict):
    """A StructLog processor to populate event dict with batch export context variables.

    More specifically, the batch export context variables are coming from Temporal:
    * workflow_run_id: The ID of the Temporal Workflow Execution running the batch export.
    * workflow_id: The ID of the Temporal Workflow running the batch export.
    * attempt: The current attempt number of the Temporal Workflow.
    * log_source_id: The batch export ID.
    * log_source: Either "batch_exports" or "batch_exports_backfill".

    We attempt to fetch the context from the activity information, and then from the workflow
    information. If both are undefined, nothing is populated. When running this processor in
    an activity or a workflow, at least one will be defined.
    """
    activity_info = attempt_to_fetch_activity_info()
    workflow_info = attempt_to_fetch_workflow_info()

    info = activity_info or workflow_info

    if info is None:
        return event_dict

    workflow_id, workflow_type, workflow_run_id, attempt = info

    if workflow_type == "backfill-batch-export":
        # This works because the WorkflowID is made up like f"{batch_export_id}-Backfill-{data_interval_end}"
        log_source_id = workflow_id.split("-Backfill")[0]
        log_source = "batch_exports_backfill"
    else:
        # This works because the WorkflowID is made up like f"{batch_export_id}-{data_interval_end}"
        # Since 'data_interval_end' is an iso formatted datetime string, it has two '-' to separate the
        # date. Plus one more leaves us at the end of right at the end of 'batch_export_id'.
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "batch_exports"

    event_dict["workflow_id"] = workflow_id
    event_dict["workflow_type"] = workflow_type
    event_dict["log_source_id"] = log_source_id
    event_dict["log_source"] = log_source
    event_dict["workflow_run_id"] = workflow_run_id
    event_dict["attempt"] = attempt

    return event_dict


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


def attempt_to_fetch_workflow_info() -> Info | None:
    """Fetch Workflow information from Temporal.

    Returns:
        None if calling outside a Workflow, else the relevant Info.
    """
    try:
        workflow_info = temporalio.workflow.info()
    except RuntimeError:
        return None
    else:
        workflow_id = workflow_info.workflow_id
        workflow_type = workflow_info.workflow_type
        workflow_run_id = workflow_info.run_id
        attempt = workflow_info.attempt

    return (workflow_id, workflow_type, workflow_run_id, attempt)


class KafkaLogProducerFromQueue:
    """Produce log messages to Kafka by getting them from a queue.

    This KafkaLogProducerFromQueue was designed to ingest logs into the ClickHouse log_entries table.
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
                security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTE1XT",
                acks="all",
            )
        )

    async def listen_and_produce(self):
        """Listen to messages in queue and produce them to Kafka as they come.

        This is designed to be ran as an asyncio.Task, as it will wait forever for the queue
        to have messages.
        """
        await self.producer.start()

        try:
            while True:
                msg = await self.queue.get()

                await self.producer.send_and_wait(self.topic, msg, key=self.key)

                self.queue.task_done()

        finally:
            await self.producer.stop()
