import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from temporalio import activity, workflow

from posthog.batch_exports.service import (
    create_batch_export_run,
    update_batch_export_run_status,
)
from posthog.kafka_client.client import (
    KafkaProducer,
)
from posthog.kafka_client.topics import KAFKA_BATCH_EXPORTS_LOGS
from posthog.models.utils import UUIDT


class PostHogWorkflow(ABC):
    """Base class for Temporal Workflows that can be executed in PostHog."""

    @classmethod
    def get_name(cls) -> str:
        """Get this workflow's name."""
        return getattr(cls, "__temporal_workflow_definition").name

    @classmethod
    def is_named(cls, name: str) -> bool:
        """Check if this workflow's name matches name.

        All temporal workflows have the __temporal_workflow_definition attribute
        injected into them by the defn decorator. We use it to access the name and
        avoid having to define it twice. If this changes in the future, we can
        update this method instead of changing every single workflow.
        """
        return cls.get_name() == name

    @staticmethod
    @abstractmethod
    def parse_inputs(inputs: list[str]) -> Any:
        """Parse inputs from the management command CLI.

        If a workflow is to be executed via the CLI it must know how to parse its
        own inputs.
        """
        return NotImplemented


class BatchExportLogRecord(logging.LogRecord):
    """Subclass of LogRecord with BatchExport parameters."""

    def __init__(
        self, *args, team_id: int, export_type: str, batch_export_id: str, data_interval_end: dt.datetime, **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.team_id = team_id
        self.export_type = export_type
        self.batch_export_id = batch_export_id
        self.data_interval_end = data_interval_end


class KafkaLoggingHandler(logging.Handler):
    """Emit logs to Kafka topic for ClickHouse Ingestion"""

    def __init__(self):
        super().__init__()
        self._producer = None

    @property
    def producer(self):
        """Return a KafkaProducer used to emit logs to Kafka."""
        if self._producer is None:
            self._producer = KafkaProducer()
        return self._producer

    def emit(
        self,
        record: logging.LogRecord,
    ):
        """Emit BatchExportLogRecord to Kafka."""
        if not isinstance(record, BatchExportLogRecord):
            # We don't handle logging.LogRecord.
            return

        timestamp_str = dt.datetime.fromtimestamp(record.created).isoformat().replace("+00:00", "")
        data_interval_end_str = record.data_interval_end.isoformat().replace("+00:00", "")

        entry = {
            "id": str(UUIDT()),
            "export_type": record.export_type,
            "team_id": record.team_id,
            "batch_export_id": record.batch_export_id,
            "data_interval_end": data_interval_end_str,
            "level": record.levelname,
            "message": self.format(record),
            "timestamp": timestamp_str,
        }

        try:
            self.producer.produce(KAFKA_BATCH_EXPORTS_LOGS, data=entry)
            # This will block waiting for messages to flush.
            # Eventually, we can squeeze out performance by using a QueueHandler.
            self.producer.close()
        except Exception:
            self.handleError(record)


def setup_logging(
    logger: logging.Logger | str,
    team_id: int,
    export_type: str,
    batch_export_id: str,
    data_interval_end: dt.datetime | str,
) -> None:
    """Setup logging of BatchExports by populating handlers and record factory.

    We setup two handlers:
    * A KafkaLoggingHandler to send logs to a Kafka topic for ingestion into ClickHouse.
    * A StreamHandler for WARNING and higher level logs to aid with debugging.

    Args:
        logger: The logger or the name of the logger to be populated with previously mentioned handlers.
        team_id: The team id the BatchExport is running for.
        batch_export_id: The id of the running BatchExport.
        data_interval_end: Used to identify the specific BatchExport run.
    """
    if isinstance(logger, str):
        logger = logging.getLogger(logger)

    # I can't find a good place to disable these.
    # We don't want to leak the entire info into the message.
    activity.logger.activity_info_on_message = False
    workflow.logger.workflow_info_on_message = False

    if len(logger.handlers) != 0:
        # We do not want to add these handlers more than once.
        return

    kafka_handler = KafkaLoggingHandler()
    kafka_handler.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.WARNING)

    logger.addHandler(kafka_handler)
    logger.addHandler(stream_handler)

    data_interval_end_dt = (
        data_interval_end
        if isinstance(data_interval_end, dt.datetime)
        else dt.datetime.fromisoformat(data_interval_end)
    )

    def batch_export_log_record_factory(*args, **kwargs) -> BatchExportLogRecord:
        """Return a subclass of LogRecord to be ingested by Kafka."""
        record = BatchExportLogRecord(
            *args,
            team_id=team_id,
            export_type=export_type,
            batch_export_id=batch_export_id,
            data_interval_end=data_interval_end_dt,
            **kwargs,
        )
        return record

    logging.setLogRecordFactory(batch_export_log_record_factory)


@dataclass
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


@activity.defn
async def create_export_run(inputs: CreateBatchExportRunInputs) -> str:
    """Activity that creates an BatchExportRun.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.
    """
    activity.logger.info(f"Creating BatchExportRun model instance in team {inputs.team_id}.")

    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(create_batch_export_run)(  # type: ignore
        batch_export_id=UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )

    activity.logger.info(f"Created BatchExportRun {run.id} in team {inputs.team_id}.")

    return str(run.id)


@dataclass
class UpdateBatchExportRunStatusInputs:
    """Inputs to the update_export_run_status activity."""

    id: str
    status: str
    latest_error: str | None = None


@activity.defn
async def update_export_run_status(inputs: UpdateBatchExportRunStatusInputs):
    """Activity that updates the status of an BatchExportRun."""
    await sync_to_async(update_batch_export_run_status)(run_id=UUID(inputs.id), status=inputs.status, latest_error=inputs.latest_error)  # type: ignore
