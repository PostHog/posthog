from dataclasses import dataclass, field
from typing import TypedDict

from products.data_warehouse.backend.types import IncrementalField


class ForeignKey(TypedDict):
    """Represents a foreign key relationship from this table to another table."""

    column: str  # Column in this table
    target_table: str  # Referenced table name
    target_column: str  # Referenced column name


class ColumnInfo(TypedDict, total=False):
    """Column metadata including name, type, and constraints."""

    name: str
    data_type: str
    is_nullable: bool


class IndexInfo(TypedDict, total=False):
    """Index metadata for a table."""

    name: str  # Index name
    columns: list[str]  # Columns in the index
    is_unique: bool  # Whether the index enforces uniqueness
    is_primary: bool  # Whether this is the primary key index


@dataclass
class SourceSchema:
    name: str
    supports_incremental: bool
    supports_append: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    row_count: int | None = None
    primary_key: list[str] | None = None  # List of column names forming the primary key
    foreign_keys: list[ForeignKey] | None = None  # Foreign key relationships
    columns: list[ColumnInfo] | None = None  # Column metadata
    indexes: list[IndexInfo] | None = None  # Index metadata
