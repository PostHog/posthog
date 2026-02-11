from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

from .constants import ADVERTISERS, CAMPAIGN_GROUPS, CAMPAIGN_STATS_DAILY, CAMPAIGNS, CONVERSION_TRACKERS, CREATIVES


@dataclass
class StackAdaptEndpointConfig:
    fields: list[IncrementalField]
    partition_keys: list[str]
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


ENDPOINT_CONFIGS: dict[str, StackAdaptEndpointConfig] = {
    ADVERTISERS: StackAdaptEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        partition_keys=["created_at"],
        primary_keys=["id"],
    ),
    CAMPAIGN_GROUPS: StackAdaptEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        partition_keys=["created_at"],
        primary_keys=["id"],
    ),
    CAMPAIGNS: StackAdaptEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        partition_keys=["created_at"],
        primary_keys=["id"],
    ),
    CAMPAIGN_STATS_DAILY: StackAdaptEndpointConfig(
        fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_keys=["date"],
        primary_keys=["campaign_id", "date"],
    ),
    CREATIVES: StackAdaptEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        partition_keys=["created_at"],
        primary_keys=["id"],
    ),
    CONVERSION_TRACKERS: StackAdaptEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        partition_keys=["created_at"],
        primary_keys=["id"],
    ),
}
