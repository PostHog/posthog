import dataclasses
from typing import Any
from collections.abc import Iterable
from dlt.common.data_types.typing import TDataType


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Iterable[Any]
    primary_keys: list[str] | None
    column_hints: dict[str, TDataType | None] | None = None  # Legacy support for DLT sources
