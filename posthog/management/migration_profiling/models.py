"""Data models for migration operation profiling.

The JSONL written by ``profile_migrations`` is the source of truth for the
analyze command — the dataclasses below define its on-disk schema. Bump
``SCHEMA_VERSION`` when changing field names or semantics so the analyze
command can warn on old captures instead of silently misreporting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 1
SQL_TRUNCATION_LIMIT = 4096


@dataclass
class SqlRecord:
    sql: str
    sql_truncated: bool
    params_repr: str | None
    duration_ms: float
    source: Literal["schema_editor", "cursor"]
    ts_offset_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpRecord:
    database: str
    app_label: str
    migration_name: str
    operation_index: int
    operation_type: str
    describe: str
    started_at: str
    duration_ms: float = 0.0
    sql_count: int = 0
    sql_total_ms: float = 0.0
    sql_truncated_count: int = 0
    is_runpython: bool = False
    is_state_only: bool = False
    parent_op_index: int | None = None
    error: str | None = None
    sql_statements: list[SqlRecord] = field(default_factory=list)
    # Per-op-type structured metadata (model_name, field_name, index_name, ...).
    # Kept in a sub-dict so we don't bloat the top-level schema with
    # per-op-type optional columns; analyze reads what's there.
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["sql_statements"] = [s.to_dict() if isinstance(s, SqlRecord) else s for s in self.sql_statements]
        return out
