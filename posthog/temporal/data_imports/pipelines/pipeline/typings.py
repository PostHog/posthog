import dataclasses
from collections.abc import Iterable
from typing import Any, Literal

from dlt.common.data_types.typing import TDataType
from structlog.types import FilteringBoundLogger

from posthog.warehouse.types import IncrementalFieldType

SortMode = Literal["asc", "desc"]
PartitionMode = Literal["md5", "numerical", "datetime"]
PartitionFormat = Literal["month", "day"]


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Iterable[Any]
    primary_keys: list[str] | None
    column_hints: dict[str, TDataType | None] | None = None  # Legacy support for DLT sources
    partition_count: int | None = None
    partition_size: int | None = None
    partition_keys: list[str] | None = None
    """Override partition keys at a source level"""
    partition_mode: PartitionMode | None = None
    """Override partition mode at a source level"""
    partition_format: PartitionFormat | None = None
    """Override partition format at a source level"""
    sort_mode: SortMode | None = "asc"
    """our source typically return data in ascending timestamp order, but some (eg Stripe) do not"""
    rows_to_sync: int | None = None
    has_duplicate_primary_keys: bool | None = None
    """Whether incremental tables have non-unique primary keys"""


@dataclasses.dataclass
class SourceInputs:
    """Contextual info required by a source to actually run"""

    schema_name: str
    schema_id: str
    team_id: int
    should_use_incremental_field: bool
    db_incremental_field_last_value: Any | None
    db_incremental_field_earliest_value: Any | None
    incremental_field: str | None
    incremental_field_type: IncrementalFieldType | None
    job_id: str
    logger: FilteringBoundLogger
