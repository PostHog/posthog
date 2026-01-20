import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from django.conf import settings

from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import _KafkaProducer
from posthog.kafka_client.topics import KAFKA_WAREHOUSE_PIPELINES_EXPORT_SIGNALS
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3_batch_writer import BatchWriteResult
from posthog.utils import SingletonDecorator

SyncTypeLiteral = Literal["full_refresh", "incremental", "append"]

# TODO: Move this to posthog/kafka_client/client.py before rollout
_WarpStreamKafkaProducer = SingletonDecorator(_KafkaProducer)


def _warpstream_kafka_producer() -> _KafkaProducer:
    return _WarpStreamKafkaProducer(
        kafka_hosts=settings.WAREHOUSE_PIPELINES_KAFKA_HOSTS,
        kafka_security_protocol=settings.WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL,
    )


@dataclass
class ExportSignalMessage:
    team_id: int
    job_id: str
    schema_id: str
    source_id: str
    resource_name: str
    run_uuid: str
    batch_index: int
    s3_path: str
    row_count: int
    byte_size: int
    is_final_batch: bool
    total_batches: Optional[int]
    total_rows: Optional[int]
    sync_type: SyncTypeLiteral
    data_folder: Optional[str]
    schema_path: Optional[str]
    timestamp_ns: int = field(default_factory=time.time_ns)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KafkaBatchProducer:
    _team_id: int
    _job_id: str
    _schema_id: str
    _source_id: str
    _resource_name: str
    _sync_type: SyncTypeLiteral
    _run_uuid: str
    _logger: FilteringBoundLogger
    _producer: Any
    _pending_futures: list[Any]

    def __init__(
        self,
        team_id: int,
        job_id: str,
        schema_id: str,
        source_id: str,
        resource_name: str,
        sync_type: SyncTypeLiteral,
        run_uuid: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._team_id = team_id
        self._job_id = job_id
        self._schema_id = schema_id
        self._source_id = source_id
        self._resource_name = resource_name
        self._sync_type = sync_type
        self._run_uuid = run_uuid
        self._logger = logger
        self._producer = _warpstream_kafka_producer()
        self._pending_futures = []

    def _get_key(self) -> str:
        return f"{self._team_id}:{self._schema_id}"  # we want ordering across multiple runs for the same schema

    def send_batch_notification(
        self,
        batch_result: BatchWriteResult,
        is_final_batch: bool = False,
        total_batches: Optional[int] = None,
        total_rows: Optional[int] = None,
        data_folder: Optional[str] = None,
        schema_path: Optional[str] = None,
    ) -> None:
        message = ExportSignalMessage(
            team_id=self._team_id,
            job_id=self._job_id,
            schema_id=self._schema_id,
            source_id=self._source_id,
            resource_name=self._resource_name,
            run_uuid=self._run_uuid,
            batch_index=batch_result.batch_index,
            s3_path=batch_result.s3_path,
            row_count=batch_result.row_count,
            byte_size=batch_result.byte_size,
            is_final_batch=is_final_batch,
            total_batches=total_batches,
            total_rows=total_rows,
            sync_type=self._sync_type,
            data_folder=data_folder,
            schema_path=schema_path,
            timestamp_ns=batch_result.timestamp_ns,
        )

        self._logger.debug(
            "Sending batch notification to Kafka",
            batch_index=batch_result.batch_index,
            is_final_batch=is_final_batch,
        )

        future = self._producer.produce(
            topic=KAFKA_WAREHOUSE_PIPELINES_EXPORT_SIGNALS,
            data=message.to_dict(),
            key=self._get_key(),
        )
        self._pending_futures.append(future)

    def flush(self, timeout: Optional[float] = None) -> int:
        self._logger.debug(f"Flushing {len(self._pending_futures)} pending Kafka messages")
        self._producer.flush(timeout=timeout)

        errors = 0
        for future in self._pending_futures:
            try:
                future.get(timeout=0)
            except Exception as e:
                capture_exception(e)
                errors += 1

        flushed_count = len(self._pending_futures)
        self._pending_futures = []

        if errors > 0:
            self._logger.warning(f"Flushed {flushed_count} messages with {errors} errors")
        else:
            self._logger.debug(f"Successfully flushed {flushed_count} messages")

        return (
            flushed_count - errors
        )  # TODO: handle errors while flushing, this needs to be done before rollout but postponing the implementation until deciding how to handle these errors
