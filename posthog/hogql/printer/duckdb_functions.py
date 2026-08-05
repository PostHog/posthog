"""DuckDB-specific function mappings that override the Postgres defaults.

These mappings are merged on top of the Postgres mappings in ``DuckDBPrinter``.
DuckDB is Postgres-wire compatible but ships a number of native functions that
produce cleaner or faster output than the Postgres equivalents we emit by default.
"""

from collections.abc import Callable

from posthog.hogql.errors import QueryError

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
    "range": "range",
    # ClickHouse's JSON_VALUE takes a real JSONPath argument, which DuckDB's
    # json_extract_string accepts directly.
    "JSON_VALUE": "json_extract_string",
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


def _handle_tuple(args: list[str]) -> str:
    # DuckDB cannot CREATE TABLE from an unnamed struct (row(...)), which is exactly
    # what shadow materialization does with every query result, so name the fields.
    fields = ", ".join(f"f{index + 1} := {arg}" for index, arg in enumerate(args))
    return f"struct_pack({fields})"


def _handle_tuple_element(args: list[str]) -> str:
    # struct_extract rejects integer keys on named structs; struct_extract_at is
    # 1-based like ClickHouse's tupleElement and works on both.
    if args[1].isdigit():
        return f"struct_extract_at({args[0]}, {args[1]})"
    return f"struct_extract({args[0]}, {args[1]})"


def _handle_multiply(args: list[str]) -> str:
    return f"({args[0]} * {args[1]})"


def _handle_not(args: list[str]) -> str:
    return f"(NOT {args[0]})"


def _handle_current_timestamp(args: list[str]) -> str:
    return "CURRENT_TIMESTAMP"


# ClickHouse's domain() is a URL parser; DuckDB has no URL functions, so extract the
# host (optionally skipping scheme and userinfo, stopping at port/path/query) by regex.
_DOMAIN_REGEX = "^(?:[^/@:]+://)?(?:[^/@]+@)?([^/:?#]+)"


def _handle_domain(args: list[str]) -> str:
    return f"regexp_extract({args[0]}, '{_DOMAIN_REGEX}', 1)"


def _handle_parse_datetime(args: list[str]) -> str:
    if len(args) != 2:
        raise QueryError("parseDateTime with a timezone argument is not supported in the DuckDB dialect.")
    return f"strptime({args[0]}, {args[1]})"


def _handle_array_filter(args: list[str]) -> str:
    if len(args) != 2:
        raise QueryError("arrayFilter over multiple arrays is not supported in the DuckDB dialect.")
    # ClickHouse takes (lambda, array); DuckDB's list_filter takes (array, lambda).
    return f"list_filter({args[1]}, {args[0]})"


def _handle_array_first(args: list[str]) -> str:
    if len(args) != 2:
        raise QueryError("arrayFirst over multiple arrays is not supported in the DuckDB dialect.")
    return f"(list_filter({args[1]}, {args[0]}))[1]"


def _handle_json_extract_keys_and_values_raw(args: list[str]) -> str:
    if len(args) != 1:
        raise QueryError("JSONExtractKeysAndValuesRaw with a path argument is not supported in the DuckDB dialect.")
    # json_transform's structure argument is itself JSON, so the MAP type is a quoted JSON string.
    return f"map_entries(json_transform({args[0]}, '\"MAP(VARCHAR, JSON)\"'))"


DUCKDB_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "argMaxIf": _handle_arg_max_if,
    "argMinIf": _handle_arg_min_if,
    "dateAdd": _handle_date_add,
    "groupUniqArray": _handle_group_uniq_array,
    "groupUniqArrayIf": _handle_group_uniq_array_if,
    "tuple": _handle_tuple,
    "tupleElement": _handle_tuple_element,
    "multiply": _handle_multiply,
    "not": _handle_not,
    "current_timestamp": _handle_current_timestamp,
    "domain": _handle_domain,
    "parseDateTime": _handle_parse_datetime,
    "arrayFilter": _handle_array_filter,
    "arrayFirst": _handle_array_first,
    "JSONExtractKeysAndValuesRaw": _handle_json_extract_keys_and_values_raw,
}

DUCKDB_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    k.lower(): v for k, v in DUCKDB_FUNCTION_HANDLERS.items()
}
