"""DuckDB-specific function mappings that override the Postgres defaults.

These mappings are merged on top of the Postgres mappings in ``DuckDBPrinter``.
DuckDB is Postgres-wire compatible but ships a number of native functions that
produce cleaner or faster output than the Postgres equivalents we emit by default.
"""

from collections.abc import Callable

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
    "argMax": "arg_max",
    "argMin": "arg_min",
    "dateTrunc": "date_trunc",
    "tuple": "row",
    "range": "range",
}

DUCKDB_FUNCTION_RENAMES_LOWER: dict[str, str] = {k.lower(): v for k, v in DUCKDB_FUNCTION_RENAMES.items()}


def _handle_arg_max_if(args: list[str]) -> str:
    return f"arg_max({args[0]}, {args[1]}) FILTER (WHERE {args[2]})"


def _handle_arg_min_if(args: list[str]) -> str:
    return f"arg_min({args[0]}, {args[1]}) FILTER (WHERE {args[2]})"


def _handle_date_add(args: list[str]) -> str:
    if len(args) == 2:
        return f"date_add({args[0]}, {args[1]})"

    interval = f"CAST((CAST({args[1]} AS VARCHAR) || ' ' || CAST({args[0]} AS VARCHAR)) AS INTERVAL)"
    return f"date_add({args[2]}, {interval})"


def _handle_group_uniq_array(args: list[str]) -> str:
    return f"list(DISTINCT {args[0]})"


def _handle_group_uniq_array_if(args: list[str]) -> str:
    return f"list(DISTINCT {args[0]}) FILTER (WHERE {args[1]})"


def _handle_tuple_element(args: list[str]) -> str:
    return f"struct_extract({args[0]}, {args[1]})"


def _handle_multiply(args: list[str]) -> str:
    return f"({args[0]} * {args[1]})"


def _handle_not(args: list[str]) -> str:
    return f"(NOT {args[0]})"


def _handle_like(args: list[str]) -> str:
    return f"({args[0]} LIKE {args[1]})"


def _handle_current_timestamp(args: list[str]) -> str:
    return "CURRENT_TIMESTAMP"


DUCKDB_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "argMaxIf": _handle_arg_max_if,
    "argMinIf": _handle_arg_min_if,
    "dateAdd": _handle_date_add,
    "groupUniqArray": _handle_group_uniq_array,
    "groupUniqArrayIf": _handle_group_uniq_array_if,
    "tupleElement": _handle_tuple_element,
    "multiply": _handle_multiply,
    "not": _handle_not,
    "like": _handle_like,
    "current_timestamp": _handle_current_timestamp,
}

DUCKDB_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    k.lower(): v for k, v in DUCKDB_FUNCTION_HANDLERS.items()
}
