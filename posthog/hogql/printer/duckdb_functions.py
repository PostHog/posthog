"""DuckDB-specific function renames that override the Postgres defaults.

These mappings are merged on top of ``POSTGRES_FUNCTION_RENAMES_LOWER`` in
``DuckDBPrinter._get_function_renames``. DuckDB is Postgres-wire compatible but
ships a number of native functions that produce cleaner or faster output than
the Postgres equivalents we emit by default.
"""

# HogQL name → DuckDB target name. Overlays POSTGRES_FUNCTION_RENAMES.
DUCKDB_FUNCTION_RENAMES: dict[str, str] = {
    # ClickHouse's ``any`` is "pick any row"; DuckDB has a native ``any_value`` aggregator.
    # Postgres approximates this with ``MIN``, which is not semantically equivalent — it
    # deterministically picks the smallest value rather than an arbitrary one.
    "any": "any_value",
    # Native type introspection; Postgres uses ``pg_typeof`` which prints differently.
    "toTypeName": "typeof",
    # DuckDB's ``strftime`` takes strftime-style format strings directly (same patterns HogQL uses)
    # whereas Postgres's ``TO_CHAR`` uses its own pattern language.
    "formatDateTime": "strftime",
    # Postgres has a custom handler for endsWith that falls back to a ``RIGHT()`` comparison;
    # DuckDB ships ``ends_with`` natively.
    "endsWith": "ends_with",
}

DUCKDB_FUNCTION_RENAMES_LOWER: dict[str, str] = {k.lower(): v for k, v in DUCKDB_FUNCTION_RENAMES.items()}
