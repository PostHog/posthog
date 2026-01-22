import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from django.conf import settings

from posthog.kafka_client.client import _KafkaProducer
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.utils import SingletonDecorator

SyncTypeLiteral = Literal["full_refresh", "incremental", "append"]

# TODO: Move this to posthog/kafka_client/client.py before rollout
_WarpStreamKafkaProducer = SingletonDecorator(_KafkaProducer)


def get_warpstream_kafka_producer() -> _KafkaProducer:
    """Get a singleton Kafka producer configured for WarpStream/warehouse pipelines."""
    return _WarpStreamKafkaProducer(
        kafka_hosts=settings.WAREHOUSE_PIPELINES_KAFKA_HOSTS,
        kafka_security_protocol=settings.WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL,
    )


@dataclass
class ExportSignalMessage:
    """Message structure for export signals sent to Kafka."""

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
    primary_keys: Optional[list[str]]
    is_resume: bool = False
    timestamp_ns: int = field(default_factory=time.time_ns)
    partition_count: Optional[int] = None
    partition_size: Optional[int] = None
    partition_keys: Optional[list[str]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_mode: Optional[PartitionMode] = None
    is_first_ever_sync: bool = False
    cumulative_row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportSignalMessage":
        return cls(
            team_id=data["team_id"],
            job_id=data["job_id"],
            schema_id=data["schema_id"],
            source_id=data["source_id"],
            resource_name=data["resource_name"],
            run_uuid=data["run_uuid"],
            batch_index=data["batch_index"],
            s3_path=data["s3_path"],
            row_count=data["row_count"],
            byte_size=data["byte_size"],
            is_final_batch=data["is_final_batch"],
            total_batches=data.get("total_batches"),
            total_rows=data.get("total_rows"),
            sync_type=data["sync_type"],
            data_folder=data.get("data_folder"),
            schema_path=data.get("schema_path"),
            primary_keys=data.get("primary_keys"),
            is_resume=data.get("is_resume", False),
            timestamp_ns=data.get("timestamp_ns", time.time_ns()),
            partition_count=data.get("partition_count"),
            partition_size=data.get("partition_size"),
            partition_keys=data.get("partition_keys"),
            partition_format=data.get("partition_format"),
            partition_mode=data.get("partition_mode"),
            is_first_ever_sync=data.get("is_first_ever_sync", False),
            cumulative_row_count=data.get("cumulative_row_count", 0),
        )
