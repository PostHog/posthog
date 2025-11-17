import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, ClassVar, Literal, Optional, Protocol, TypeVar

from dlt.common.data_types.typing import TDataType
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.types import IncrementalFieldType

SortMode = Literal["asc", "desc"]
PartitionMode = Literal["md5", "numerical", "datetime"]
PartitionFormat = Literal["month", "week", "day", "hour"]


class _Dataclass(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]


ResumableData = TypeVar("ResumableData", bound=_Dataclass)


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Callable[[], Iterable[Any]]
    primary_keys: list[str] | None
    column_hints: dict[str, TDataType | None] | None = None  # Legacy support for DLT sources
    partition_count: Optional[int] = None
    partition_size: Optional[int] = None
    partition_keys: Optional[list[str]] = None
    """Override partition keys at a source level"""
    partition_mode: Optional[PartitionMode] = None
    """Override partition mode at a source level"""
    partition_format: Optional[PartitionFormat] = None
    """Override partition format at a source level"""
    sort_mode: Optional[SortMode] = "asc"
    """our source typically return data in ascending timestamp order, but some (eg Stripe) do not"""
    rows_to_sync: Optional[int] = None
    has_duplicate_primary_keys: Optional[bool] = None
    """Whether incremental tables have non-unique primary keys"""


@dataclasses.dataclass
class SourceInputs:
    """Contextual info required by a source to actually run"""

    schema_name: str
    schema_id: str
    team_id: int
    should_use_incremental_field: bool
    db_incremental_field_last_value: Optional[Any]
    db_incremental_field_earliest_value: Optional[Any]
    incremental_field: Optional[str]
    incremental_field_type: Optional[IncrementalFieldType]
    job_id: str
    logger: FilteringBoundLogger
