from collections.abc import Callable

from posthog.hogql.printer.postgres_functions import (
    _handle_e,
    _handle_empty,
    _handle_ends_with,
    _handle_if,
    _handle_is_not_null,
    _handle_is_null,
    _handle_log2,
    _handle_multi_if,
    _handle_noop,
    _handle_not_empty,
    _handle_to_last_day_of_week,
    _handle_to_yyyymm,
    _handle_to_yyyymmdd,
    _handle_to_yyyymmddhhmmss,
    _handle_today,
    _handle_uniq,
    _handle_yesterday,
    _make_cast_handler,
    _make_date_trunc_handler,
    _make_extract_handler,
)

# Snowflake function maps. Unlike MySQL/Postgres-direct, the Snowflake printer does
# NOT fall back to the Postgres maps — these are the complete surface. Anything not
# in a rename, handler, or passthrough raises "not supported in the Snowflake
# dialect". Handlers that emit standard SQL valid in Snowflake are imported from
# postgres_functions; the rest are defined here.
#
# NOTE: dateDiff and formatDateTime are NOT here — their first argument (the date
# part / format string) must be inlined as a literal, not bound as a parameter, so
# they are intercepted in SnowflakePrinter.visit_call where the raw AST is available.

# Simple 1:1 name swaps (args unchanged). ClickHouse/HogQL name → Snowflake name.
SNOWFLAKE_FUNCTION_RENAMES: dict[str, str] = {
    "ifNull": "COALESCE",
    "groupArray": "ARRAY_AGG",
    "fromUnixTimestamp": "TO_TIMESTAMP",  # Snowflake reads a bare number as seconds
    "replaceAll": "REPLACE",
    "replaceRegexpAll": "REGEXP_REPLACE",  # Snowflake replaces all occurrences by default
    "arrayStringConcat": "ARRAY_TO_STRING",
    "toTypeName": "TYPEOF",
    "any": "MIN",  # no arbitrary-value aggregate; MIN is the portable fallback
    "startsWith": "STARTSWITH",  # Postgres uses starts_with; Snowflake's builtin has no underscore
    "now": "CURRENT_TIMESTAMP",  # Snowflake has no NOW()
    "pow": "POWER",  # Snowflake has POWER, not POW
}


# --- Date arithmetic: Snowflake cannot multiply an INTERVAL, so use DATEADD. ---


def _make_dateadd_handler(unit: str, negate: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        amount = f"-({args[1]})" if negate else args[1]
        return f"DATEADD('{unit}', {amount}, {args[0]})"

    return handler


def _make_snowflake_interval_handler(unit: str) -> Callable[[list[str]], str]:
    # Snowflake interval literals can't be parameterized or built from an
    # expression — the count must be a literal. Fine for the common toIntervalX(7)
    # case; a non-literal argument produces SQL Snowflake will reject.
    def handler(args: list[str]) -> str:
        return f"INTERVAL '{args[0]} {unit}'"

    return handler


def _handle_to_last_day_of_month(args: list[str]) -> str:
    return f"CAST(LAST_DAY({args[0]}) AS DATE)"


def _handle_to_unix_timestamp(args: list[str]) -> str:
    return f"CAST(DATE_PART('epoch_second', {args[0]}) AS BIGINT)"


# --- JSON: Snowflake reads semi-structured data via PARSE_JSON + bracket paths. ---


def _snowflake_json_path(args: list[str]) -> str:
    # args = (json, key1, key2, ...). Bracket access accepts an expression key, so
    # the bound key params work; chaining walks nested objects/arrays.
    expr = f"PARSE_JSON({args[0]})"
    for key in args[1:]:
        expr = f"{expr}[{key}]"
    return expr


def _make_json_extract_cast_handler(snowflake_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"CAST({_snowflake_json_path(args)} AS {snowflake_type})"

    return handler


def _handle_json_extract_raw(args: list[str]) -> str:
    return _snowflake_json_path(args)


def _handle_json_length(args: list[str]) -> str:
    return f"ARRAY_SIZE(PARSE_JSON({args[0]}))"


# --- Strings ---


def _handle_match(args: list[str]) -> str:
    # ClickHouse match() is a partial (search) match; Snowflake REGEXP_LIKE is
    # whole-string, so use REGEXP_INSTR != 0 to preserve "found anywhere" semantics.
    return f"(REGEXP_INSTR({args[0]}, {args[1]}) != 0)"


def _handle_split_by(args: list[str]) -> str:
    # splitByString(sep, str) / splitByChar(sep, str) → SPLIT(str, sep) — args swap
    return f"SPLIT({args[1]}, {args[0]})"


def _handle_replace_one(args: list[str]) -> str:
    # Snowflake REGEXP_REPLACE replaces all by default; position=1, occurrence=1
    # restricts it to the first match (matching replaceOne/replaceRegexpOne).
    return f"REGEXP_REPLACE({args[0]}, {args[1]}, {args[2]}, 1, 1)"


# --- Math ---


def _handle_rand(args: list[str]) -> str:
    # Snowflake RANDOM() returns a signed integer; UNIFORM gives the [0,1) float
    # the Postgres backend's random() rename produced.
    return "UNIFORM(0::float, 1::float, RANDOM())"


def _handle_log10(args: list[str]) -> str:
    return f"LOG(10, {args[0]})"


def _handle_log(args: list[str]) -> str:
    # HogQL log() is natural log; Snowflake LOG requires a base, so use LN.
    return f"LN({args[0]})"


# --- Aggregate *If combinators: Snowflake has no FILTER (WHERE) clause. ---


def _make_agg_if_handler(snowflake_fn: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        *agg_args, condition = args
        return f"{snowflake_fn}(CASE WHEN {condition} THEN {', '.join(agg_args)} END)"

    return handler


def _handle_count(args: list[str]) -> str:
    # HogQL's argless count() means "count all rows", but Snowflake rejects a bare COUNT() —
    # it must be COUNT(*). count(expr) passes through unchanged.
    return "count(*)" if not args else f"count({', '.join(args)})"


def _handle_count_if(args: list[str]) -> str:
    if len(args) == 1:
        return f"COUNT_IF({args[0]})"
    return f"COUNT(CASE WHEN {args[1]} THEN {args[0]} END)"


def _handle_uniq_if(args: list[str]) -> str:
    *agg_args, condition = args
    return f"COUNT(DISTINCT CASE WHEN {condition} THEN {', '.join(agg_args)} END)"


# Functions needing custom rendering: lowercased-name → callable(rendered_args) → SQL.
SNOWFLAKE_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    # Type conversions (Snowflake type synonyms; no UUID type → VARCHAR)
    "toDate": _make_cast_handler("DATE"),
    "toDateTime": _make_cast_handler("TIMESTAMP"),
    "toDateTime64": _make_cast_handler("TIMESTAMP"),
    "toString": _make_cast_handler("VARCHAR"),
    "toInt": _make_cast_handler("BIGINT"),
    "toIntOrZero": _make_cast_handler("BIGINT"),
    "toIntOrDefault": _make_cast_handler("BIGINT"),
    "toFloat": _make_cast_handler("DOUBLE"),
    "toFloatOrZero": _make_cast_handler("DOUBLE"),
    "toFloatOrDefault": _make_cast_handler("DOUBLE"),
    "toBool": _make_cast_handler("BOOLEAN"),
    "toDecimal": _make_cast_handler("DECIMAL"),
    "toUUID": _make_cast_handler("VARCHAR"),
    # Date extraction (Snowflake's EXTRACT unit names differ from Postgres')
    "toYear": _make_extract_handler("YEAR"),
    "toQuarter": _make_extract_handler("QUARTER"),
    "toMonth": _make_extract_handler("MONTH"),
    "toDayOfMonth": _make_extract_handler("DAY"),
    "toDayOfWeek": _make_extract_handler("dayofweekiso"),
    "toDayOfYear": _make_extract_handler("dayofyear"),
    "toHour": _make_extract_handler("HOUR"),
    "toMinute": _make_extract_handler("MINUTE"),
    "toSecond": _make_extract_handler("SECOND"),
    "toISOWeek": _make_extract_handler("weekiso"),
    "toISOYear": _make_extract_handler("yearofweekiso"),
    "toUnixTimestamp": _handle_to_unix_timestamp,
    # Date formatting to integers
    "toYYYYMM": _handle_to_yyyymm,
    "toYYYYMMDD": _handle_to_yyyymmdd,
    "toYYYYMMDDhhmmss": _handle_to_yyyymmddhhmmss,
    # Date truncation (WEEK_START session param governs week boundaries)
    "toMonday": _make_date_trunc_handler("week", cast_to_date=True),
    "toLastDayOfMonth": _handle_to_last_day_of_month,
    "toLastDayOfWeek": _handle_to_last_day_of_week,
    # Date generators
    "today": _handle_today,
    "yesterday": _handle_yesterday,
    # Intervals
    "toIntervalSecond": _make_snowflake_interval_handler("second"),
    "toIntervalMinute": _make_snowflake_interval_handler("minute"),
    "toIntervalHour": _make_snowflake_interval_handler("hour"),
    "toIntervalDay": _make_snowflake_interval_handler("day"),
    "toIntervalWeek": _make_snowflake_interval_handler("week"),
    "toIntervalMonth": _make_snowflake_interval_handler("month"),
    "toIntervalQuarter": _make_snowflake_interval_handler("quarter"),
    "toIntervalYear": _make_snowflake_interval_handler("year"),
    # Date arithmetic
    "addSeconds": _make_dateadd_handler("second"),
    "addMinutes": _make_dateadd_handler("minute"),
    "addHours": _make_dateadd_handler("hour"),
    "addDays": _make_dateadd_handler("day"),
    "addWeeks": _make_dateadd_handler("week"),
    "addMonths": _make_dateadd_handler("month"),
    "addQuarters": _make_dateadd_handler("quarter"),
    "addYears": _make_dateadd_handler("year"),
    "subtractSeconds": _make_dateadd_handler("second", negate=True),
    "subtractMinutes": _make_dateadd_handler("minute", negate=True),
    "subtractHours": _make_dateadd_handler("hour", negate=True),
    "subtractDays": _make_dateadd_handler("day", negate=True),
    "subtractWeeks": _make_dateadd_handler("week", negate=True),
    "subtractMonths": _make_dateadd_handler("month", negate=True),
    "subtractQuarters": _make_dateadd_handler("quarter", negate=True),
    "subtractYears": _make_dateadd_handler("year", negate=True),
    # Conditional
    "if": _handle_if,
    "multiIf": _handle_multi_if,
    # Null / empty
    "empty": _handle_empty,
    "notEmpty": _handle_not_empty,
    "isNull": _handle_is_null,
    "isNotNull": _handle_is_not_null,
    "assumeNotNull": _handle_noop,
    "toNullable": _handle_noop,
    # JSON
    "JSONExtractString": _make_json_extract_cast_handler("VARCHAR"),
    "JSONExtractRaw": _handle_json_extract_raw,
    "JSONExtractArrayRaw": _handle_json_extract_raw,
    "JSONExtractInt": _make_json_extract_cast_handler("INTEGER"),
    "JSONExtractUInt": _make_json_extract_cast_handler("INTEGER"),
    "JSONExtractFloat": _make_json_extract_cast_handler("DOUBLE"),
    "JSONExtractBool": _make_json_extract_cast_handler("BOOLEAN"),
    "JSONLength": _handle_json_length,
    # String
    "match": _handle_match,
    "splitByString": _handle_split_by,
    "splitByChar": _handle_split_by,
    "endsWith": _handle_ends_with,
    "replaceOne": _handle_replace_one,
    "replaceRegexpOne": _handle_replace_one,
    # Math
    "e": _handle_e,
    "log2": _handle_log2,
    "log10": _handle_log10,
    "log": _handle_log,
    "rand": _handle_rand,
    # Aggregation
    "uniq": _handle_uniq,
    "uniqExact": _handle_uniq,
    "count": _handle_count,
    "countIf": _handle_count_if,
    "sumIf": _make_agg_if_handler("SUM"),
    "avgIf": _make_agg_if_handler("AVG"),
    "minIf": _make_agg_if_handler("MIN"),
    "maxIf": _make_agg_if_handler("MAX"),
    "anyIf": _make_agg_if_handler("MIN"),
    "groupArrayIf": _make_agg_if_handler("ARRAY_AGG"),
    "uniqIf": _handle_uniq_if,
    "uniqExactIf": _handle_uniq_if,
}

# Standard-SQL functions valid in Snowflake verbatim. Anything not here, in a
# rename, or in a handler raises "not supported in the Snowflake dialect".
SNOWFLAKE_PASSTHROUGH_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Aggregates
        "sum",
        "avg",
        "min",
        "max",
        # Math
        "abs",
        "floor",
        "ceil",
        "round",
        "sqrt",
        "power",
        "exp",
        "ln",
        "sign",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "pi",
        "degrees",
        "radians",
        "cbrt",
        "greatest",
        "least",
        # String
        "lower",
        "upper",
        "trim",
        "ltrim",
        "rtrim",
        "substring",
        "concat",
        "length",
        "left",
        "right",
        "position",
        "reverse",
        "replace",
        "lpad",
        "rpad",
        "repeat",
        "initcap",
        "ascii",
        # Window
        "row_number",
        "rank",
        "dense_rank",
        "lag",
        "lead",
        "first_value",
        "last_value",
        "nth_value",
        # Null
        "coalesce",
        "nullif",
        # Date / time
        "date_trunc",
        # Other
        "md5",
    },
)


# Case-insensitive lookup maps — visit_call matches against node.name.lower().
SNOWFLAKE_FUNCTION_RENAMES_LOWER: dict[str, str] = {k.lower(): v for k, v in SNOWFLAKE_FUNCTION_RENAMES.items()}
SNOWFLAKE_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    k.lower(): v for k, v in SNOWFLAKE_FUNCTION_HANDLERS.items()
}
