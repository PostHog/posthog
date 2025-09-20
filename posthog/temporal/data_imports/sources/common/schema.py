from dataclasses import dataclass, field

from posthog.warehouse.types import IncrementalField


@dataclass
class SourceSchema:
    name: str
    supports_incremental: bool
    supports_append: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    row_count: int | None = None
