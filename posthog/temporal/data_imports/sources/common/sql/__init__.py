"""Shared plumbing for SQL-based data-import sources.

This package concentrates the orchestration and safety primitives that used to
be copy-pasted across every SQL source (`postgres/postgres.py`, `mysql/mysql.py`,
etc). A new SQL source should be implementable by subclassing `SQLSource` and
providing a small set of driver-specific hooks — connection, identifier quoter,
incremental-field filter, and schema/row discovery.

Only the types that existed in the old `common/sql.py` are re-exported from
this package's root so existing `from ...common.sql import Column, Table`
imports keep working. New callers should import from the submodules directly.
"""

from posthog.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    BracketIdentifierQuoter,
    IdentifierQuoter,
    InvalidIdentifierError,
)
from posthog.temporal.data_imports.sources.common.sql.implementation import TableStats
from posthog.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
    build_incremental_fields,
    initial_value_for_incremental_type,
)
from posthog.temporal.data_imports.sources.common.sql.query_builder import ParamStyle, SafeSQL, SelectQueryBuilder
from posthog.temporal.data_imports.sources.common.sql.types import (
    Column,
    ColumnType,
    Table,
    TableBase,
    TableReference,
    TableSchemas,
    resolve_detected_primary_keys,
)

__all__ = [
    "AnsiIdentifierQuoter",
    "BacktickIdentifierQuoter",
    "BracketIdentifierQuoter",
    "Column",
    "ColumnType",
    "IdentifierQuoter",
    "IncrementalFieldFilter",
    "InvalidIdentifierError",
    "ParamStyle",
    "SafeSQL",
    "SelectQueryBuilder",
    "Table",
    "TableBase",
    "TableReference",
    "TableSchemas",
    "TableStats",
    "build_incremental_fields",
    "initial_value_for_incremental_type",
    "resolve_detected_primary_keys",
]
