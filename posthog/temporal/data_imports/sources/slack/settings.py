from dataclasses import dataclass, field
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode


@dataclass
class EndpointConfig:
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    partition_format: Optional[PartitionFormat] = None


ENDPOINTS: dict[str, EndpointConfig] = {
    "$channels": EndpointConfig(),
    "$users": EndpointConfig(),
}


def messages_endpoint_config() -> EndpointConfig:
    return EndpointConfig(
        primary_keys=["channel_id", "ts"],
        partition_keys=["timestamp"],
        partition_mode="datetime",
        partition_format="week",
    )
