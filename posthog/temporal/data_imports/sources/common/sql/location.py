"""Shared per-row routing for multi-schema SQL warehouse import.

`resolve_source_location` is the single source-agnostic router every SQL driver's `build_pipeline`
delegates to, so the Postgres routing logic isn't re-derived per source.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs


class ResolvedSourceLocation(NamedTuple):
    """Where a single warehouse-import row reads from + the Delta subdir it writes to."""

    catalog: Optional[str]
    schema: Optional[str]
    table_name: str
    response_name: str


def normalize_namespace(value: Optional[str]) -> Optional[str]:
    """Empty / whitespace-only namespace means "all namespaces" — never an empty predicate."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def fill_missing_from_dotted_name(
    schema: Optional[str], table: Optional[str], display_name: str
) -> tuple[Optional[str], Optional[str]]:
    """Self-heal a missing `schema`/`table` from a dotted `display_name` (`analytics.users`).

    Shared by the sync resolver and the migration's row extractor so the "metadata-first, then split
    the dotted name" rule can't drift between them.
    """
    if (not schema or not table) and "." in display_name:
        inferred_schema, _, inferred_table = display_name.partition(".")
        schema = schema or normalize_namespace(inferred_schema)
        table = table or inferred_table or None
    return schema, table


def resolve_source_location(
    inputs: SourceInputs,
    *,
    config_namespace: Optional[str],
    config_catalog: Optional[str] = None,
    default: Optional[str] = None,
) -> ResolvedSourceLocation:
    """Resolve `(catalog, schema, table_name, response_name)` for one warehouse-import row.

    Namespace + table priority: per-row `schema_metadata` → dotted `schema_name` self-heal →
    `config_namespace` → `default`. `response_name` (the Delta subdir) comes from `dwh_storage_key`
    when present, so a migrated row keeps its legacy path — no S3 rewrite, no orphaned data.
    """
    source_schema = normalize_namespace(inputs.source_schema)
    source_table_name = inputs.source_table_name if isinstance(inputs.source_table_name, str) else None
    source_schema, source_table_name = fill_missing_from_dotted_name(
        source_schema, source_table_name, inputs.schema_name
    )

    schema = source_schema or normalize_namespace(config_namespace) or default
    table_name = source_table_name or inputs.schema_name
    catalog = (inputs.source_catalog if isinstance(inputs.source_catalog, str) else None) or config_catalog

    storage_key = inputs.dwh_storage_key if isinstance(inputs.dwh_storage_key, str) and inputs.dwh_storage_key else None
    response_name = NamingConvention.normalize_identifier(storage_key or inputs.schema_name)

    return ResolvedSourceLocation(catalog=catalog, schema=schema, table_name=table_name, response_name=response_name)
