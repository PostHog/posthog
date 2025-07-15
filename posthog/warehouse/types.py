import typing
from enum import StrEnum


class IncrementalFieldType(StrEnum):
    Integer = "integer"
    Numeric = "numeric"  # For snowflake
    DateTime = "datetime"
    Date = "date"
    Timestamp = "timestamp"
    # MongoDB specific
    ObjectID = "objectid"


class IncrementalField(typing.TypedDict):
    label: str  # Label shown in the UI
    type: IncrementalFieldType  # Field type shown in the UI
    field: str  # Actual DB field accessed
    field_type: IncrementalFieldType  # Actual DB type of the field


class PartitionSettings(typing.NamedTuple):
    """Settings used when partitioning data warehouse tables.

    Attributes:
        partition_count: Total number of partitions.
        partition_size: Number of rows to include per partition.
    """

    partition_count: int
    partition_size: int
