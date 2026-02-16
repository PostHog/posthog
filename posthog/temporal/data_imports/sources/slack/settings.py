from dataclasses import dataclass, field
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class EndpointConfig:
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    partition_format: Optional[PartitionFormat] = None


ENDPOINTS: dict[str, EndpointConfig] = {
    "_channels": EndpointConfig(),
    "_users": EndpointConfig(),
}


def messages_endpoint_config() -> EndpointConfig:
    return EndpointConfig(
        primary_keys=["channel_id", "ts"],
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_keys=["timestamp"],
        partition_mode="datetime",
        partition_format="week",
    )
