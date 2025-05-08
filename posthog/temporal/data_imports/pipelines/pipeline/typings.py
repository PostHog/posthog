import dataclasses
from collections.abc import Iterable
from typing import Any, Literal, Optional

from dlt.common.data_types.typing import TDataType

SortMode = Literal["asc", "desc"]


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Iterable[Any]
    primary_keys: list[str] | None
    column_hints: dict[str, TDataType | None] | None = None  # Legacy support for DLT sources
    partition_count: Optional[int] = None
    partition_size: Optional[int] = None
    # our source typically return data in ascending timestamp order, but some (eg Stripe) do not
    sort_mode: Optional[SortMode] = "asc"
    rows_to_sync: Optional[int] = None


PartitionMode = Literal["md5", "numerical", "datetime"]
PartitionFormat = Literal["month", "day"]
