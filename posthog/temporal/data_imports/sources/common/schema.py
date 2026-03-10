from dataclasses import dataclass, field

from products.data_warehouse.backend.types import IncrementalField


@dataclass
class SourceSchema:
    name: str
    supports_incremental: bool
    supports_append: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    row_count: int | None = None
    columns: list[tuple[str, str, bool]] = field(default_factory=list)
    foreign_keys: list[tuple[str, str, str]] = field(default_factory=list)
