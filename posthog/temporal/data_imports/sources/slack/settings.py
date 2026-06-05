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
    "$channels": EndpointConfig(),
    "$users": EndpointConfig(),
}


def messages_endpoint_config() -> EndpointConfig:
    # The runtime path in slack.py already wires incremental polling against the
    # `timestamp` column — it reads `db_incremental_field_last_value.timestamp()`
    # and passes it to Slack's `oldest` param on `conversations.history` (slack.py
    # ~line 433). Declaring `incremental_fields` here is what the schema layer
    # uses (source.py:201-204) to flip `supports_incremental` / `supports_append`
    # to True, so the channel schema can offer those sync modes in the UI instead
    # of forcing every refresh to be a full re-pull of `conversations.history`.
    return EndpointConfig(
        primary_keys=["channel_id", "ts"],
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["timestamp"],
        partition_mode="datetime",
        partition_format="week",
    )
