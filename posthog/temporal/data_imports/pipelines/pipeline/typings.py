import dataclasses
from typing import Any
from collections.abc import Iterable


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Iterable[Any]
    primary_keys: list[str] | None
