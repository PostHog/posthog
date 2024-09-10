from enum import StrEnum
from typing import TypedDict


class IncrementalFieldType(StrEnum):
    Integer = "integer"
    Numeric = "numeric"  # For snowflake
    DateTime = "datetime"
    Date = "date"
    Timestamp = "timestamp"


class IncrementalField(TypedDict):
    label: str  # Label shown in the UI
    type: IncrementalFieldType  # Field type shown in the UI
    field: str  # Actual DB field accessed
    field_type: IncrementalFieldType  # Actual DB type of the field
