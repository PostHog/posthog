"""Materialized-column types and constants the HogQL engine can import without booting Django.

The Django-side lookups (instance settings, the EE column cache) live in
posthog.clickhouse.materialized_columns, which re-exports these names for existing callers.
"""

from typing import Protocol

from posthog.property_columns import TableWithProperties

ColumnName = str
TablesWithMaterializedColumns = TableWithProperties
MATERIALIZATION_VALID_TABLES: frozenset[TablesWithMaterializedColumns] = frozenset({"events", "person", "groups"})

DMAT_STRING_COLUMN_NAME_PREFIX = "dmat_string_"
# Naming prefixes for physical materialized columns; mat_/pmat_ are minted by
# _materialized_column_name in ee/clickhouse/materialized_columns/columns.py.
MATERIALIZED_COLUMN_NAME_PREFIXES = ("mat_", "pmat_", DMAT_STRING_COLUMN_NAME_PREFIX)


class MaterializedColumn(Protocol):
    name: ColumnName
    is_nullable: bool
    has_minmax_index: bool
    has_bloom_filter_index: bool
    has_ngram_lower_index: bool
    has_bloom_filter_lower_index: bool

    @property
    def type(self) -> str: ...
