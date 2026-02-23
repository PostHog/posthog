from typing import Any, Optional

from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.topics import KAFKA_WAREHOUSE_SOURCES_JOBS
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.common import (
    ExportSignalMessage,
    SyncTypeLiteral,
    get_warpstream_kafka_producer,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult


class KafkaBatchProducer:
    _team_id: int
    _job_id: str
    _schema_id: str
    _source_id: str
    _resource_name: str
    _sync_type: SyncTypeLiteral
    _run_uuid: str
    _primary_keys: list[str] | None
    _is_resume: bool
    _logger: FilteringBoundLogger
    _producer: Any
    _pending_futures: list[Any]
    # Partitioning fields
    _partition_count: int | None
    _partition_size: int | None
    _partition_keys: list[str] | None
    _partition_format: PartitionFormat | None
    _partition_mode: PartitionMode | None
    # Partial data loading fields
    _is_first_ever_sync: bool

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
        primary_keys: list[str] | None = None,
        is_resume: bool = False,
        partition_count: int | None = None,
        partition_size: int | None = None,
        partition_keys: list[str] | None = None,
        partition_format: PartitionFormat | None = None,
        partition_mode: PartitionMode | None = None,
        is_first_ever_sync: bool = False,
    ) -> None:
        self._team_id = team_id
        self._job_id = job_id
        self._schema_id = schema_id
        self._source_id = source_id
        self._resource_name = resource_name
        self._sync_type = sync_type
        self._run_uuid = run_uuid
        self._primary_keys = primary_keys
        self._is_resume = is_resume
        self._logger = logger
        self._producer = get_warpstream_kafka_producer()
        self._pending_futures = []
        # Partitioning fields
        self._partition_count = partition_count
        self._partition_size = partition_size
        self._partition_keys = partition_keys
        self._partition_format = partition_format
        self._partition_mode = partition_mode
        # Partial data loading fields
        self._is_first_ever_sync = is_first_ever_sync

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
        cumulative_row_count: int = 0,
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
            primary_keys=self._primary_keys,
            is_resume=self._is_resume,
            timestamp_ns=batch_result.timestamp_ns,
            partition_count=self._partition_count,
            partition_size=self._partition_size,
            partition_keys=self._partition_keys,
            partition_format=self._partition_format,
            partition_mode=self._partition_mode,
            is_first_ever_sync=self._is_first_ever_sync,
            cumulative_row_count=cumulative_row_count,
        )

        self._logger.debug(
            "Sending batch notification to Kafka",
            batch_index=batch_result.batch_index,
            is_final_batch=is_final_batch,
        )

        future = self._producer.produce(
            topic=KAFKA_WAREHOUSE_SOURCES_JOBS,
            data=message.to_dict(),
            key=self._get_key(),
        )
        self._pending_futures.append(future)

    def flush(self, timeout: Optional[float] = None) -> int:
        self._logger.debug(f"Flushing {len(self._pending_futures)} pending Kafka messages")
        self._producer.flush(timeout=timeout)

        errors: list[Exception] = []
        for future in self._pending_futures:
            try:
                future.get(timeout=0)
            except Exception as e:
                capture_exception(e)
                errors.append(e)

        flushed_count = len(self._pending_futures)
        self._pending_futures = []

        if errors:
            raise Exception(f"Failed to deliver {len(errors)}/{flushed_count} Kafka messages: {errors[0]}")

        self._logger.debug(f"Successfully flushed {flushed_count} messages")
        return flushed_count
