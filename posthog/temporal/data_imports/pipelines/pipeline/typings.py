import dataclasses
from collections.abc import Iterable
from typing import Any, Literal, Optional

from dlt.common.data_types.typing import TDataType

SortMode = Literal["asc", "desc"]
PartitionMode = Literal["md5", "numerical", "datetime"]
PartitionFormat = Literal["month", "day"]


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Iterable[Any]
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
    # our source typically return data in ascending timestamp order, but some (eg Stripe) do not
    sort_mode: Optional[SortMode] = "asc"
    rows_to_sync: Optional[int] = None
