from collections.abc import Callable

# Simple 1:1 function name renames (ClickHouse name → Postgres name)
POSTGRES_FUNCTION_RENAMES: dict[str, str] = {
    "ifNull": "COALESCE",
    "groupArray": "ARRAY_AGG",
    "arrayJoin": "UNNEST",
    "JSONExtractString": "json_extract_path_text",
    "JSONExtractRaw": "json_extract_path",
    "JSONExtractArrayRaw": "json_extract_path",
    "fromUnixTimestamp": "TO_TIMESTAMP",
    "replaceAll": "REPLACE",
    "replaceRegexpAll": "REGEXP_REPLACE",
    "arrayStringConcat": "ARRAY_TO_STRING",
    "JSONLength": "json_array_length",
    "toTypeName": "pg_typeof",
    "formatDateTime": "TO_CHAR",
    "now": "NOW",
    "any": "MIN",
    "startsWith": "starts_with",
    "rand": "random",
    "generateSeries": "generate_series",
}


def _make_cast_handler(pg_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"CAST({args[0]} AS {pg_type})"

    return handler


def _make_extract_handler(unit: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"EXTRACT({unit} FROM {args[0]})"

    return handler


def _make_date_trunc_handler(unit: str, cast_to_date: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        expr = f"DATE_TRUNC('{unit}', {args[0]})"
        if cast_to_date:
            return f"CAST({expr} AS DATE)"
        return expr

    return handler


def _make_interval_handler(unit: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"({args[0]} * INTERVAL '{unit}')"

    return handler


def _make_date_add_handler(unit: str, op: str = "+") -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"({args[0]} {op} {args[1]} * INTERVAL '{unit}')"

    return handler


def _handle_to_unix_timestamp(args: list[str]) -> str:
    return f"CAST(EXTRACT(EPOCH FROM {args[0]}) AS BIGINT)"


def _handle_to_yyyymm(args: list[str]) -> str:
    return f"CAST(TO_CHAR({args[0]}, 'YYYYMM') AS INTEGER)"


def _handle_to_last_day_of_month(args: list[str]) -> str:
    return f"CAST((DATE_TRUNC('month', {args[0]}) + INTERVAL '1 month' - INTERVAL '1 day') AS DATE)"


def _handle_today(args: list[str]) -> str:
    return "CURRENT_DATE"


def _handle_yesterday(args: list[str]) -> str:
    return "(CURRENT_DATE - INTERVAL '1 day')"


def _handle_if(args: list[str]) -> str:
    return f"CASE WHEN {args[0]} THEN {args[1]} ELSE {args[2]} END"


def _handle_multi_if(args: list[str]) -> str:
    # multiIf(c1, v1, c2, v2, ..., default)
    # Pairs of (condition, value) followed by a default
    parts = ["CASE"]
    i = 0
    while i < len(args) - 1:
        parts.append(f"WHEN {args[i]} THEN {args[i + 1]}")
        i += 2
    parts.append(f"ELSE {args[-1]} END")
    return " ".join(parts)


def _handle_empty(args: list[str]) -> str:
    return f"({args[0]} IS NULL OR {args[0]} = '')"


def _handle_not_empty(args: list[str]) -> str:
    return f"({args[0]} IS NOT NULL AND {args[0]} != '')"


def _handle_is_null(args: list[str]) -> str:
    return f"({args[0]} IS NULL)"


def _handle_is_not_null(args: list[str]) -> str:
    return f"({args[0]} IS NOT NULL)"


def _handle_noop(args: list[str]) -> str:
    return args[0]


def _make_json_cast_handler(pg_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        # JSONExtractInt(json, key1, key2, ...) → CAST(json_extract_path_text(json, key1, key2, ...) AS type)
        inner_args = ", ".join(args)
        return f"CAST(json_extract_path_text({inner_args}) AS {pg_type})"

    return handler


def _handle_match(args: list[str]) -> str:
    return f"({args[0]} ~ {args[1]})"


def _handle_split_by(args: list[str]) -> str:
    # splitByString(sep, str) → STRING_TO_ARRAY(str, sep) — args are reversed
    return f"STRING_TO_ARRAY({args[1]}, {args[0]})"


def _handle_uniq(args: list[str]) -> str:
    return f"COUNT(DISTINCT {args[0]})"


def _handle_to_yyyymmdd(args: list[str]) -> str:
    return f"CAST(TO_CHAR({args[0]}, 'YYYYMMDD') AS INTEGER)"


def _handle_to_yyyymmddhhmmss(args: list[str]) -> str:
    return f"CAST(TO_CHAR({args[0]}, 'YYYYMMDDHH24MISS') AS BIGINT)"


def _handle_to_last_day_of_week(args: list[str]) -> str:
    return f"CAST((DATE_TRUNC('week', {args[0]}) + INTERVAL '6 day') AS DATE)"


def _handle_replace_one(args: list[str]) -> str:
    # Postgres REGEXP_REPLACE defaults to first occurrence only
    return f"REGEXP_REPLACE({args[0]}, {args[1]}, {args[2]})"


def _handle_count_if(args: list[str]) -> str:
    if len(args) == 1:
        return f"count(*) FILTER (WHERE {args[0]})"
    return f"count({args[0]}) FILTER (WHERE {args[1]})"


def _make_if_combinator_handler(pg_base_fn: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        agg_args = args[:-1]
        condition = args[-1]
        return f"{pg_base_fn}({', '.join(agg_args)}) FILTER (WHERE {condition})"

    return handler


def _handle_uniq_if(args: list[str]) -> str:
    agg_args = args[:-1]
    condition = args[-1]
    return f"COUNT(DISTINCT {', '.join(agg_args)}) FILTER (WHERE {condition})"


def _handle_date_diff(args: list[str]) -> str:
    # DATE_PART extracts from an INTERVAL, so both operands must be TIMESTAMP
    # (TIMESTAMP - TIMESTAMP → INTERVAL, whereas DATE - DATE → INTEGER which DATE_PART rejects)
    return f"DATE_PART({args[0]}, CAST({args[2]} AS TIMESTAMP) - CAST({args[1]} AS TIMESTAMP))"


def _handle_ends_with(args: list[str]) -> str:
    return f"(RIGHT({args[0]}, LENGTH({args[1]})) = {args[1]})"


def _handle_e(args: list[str]) -> str:
    return "exp(1)"


def _handle_log2(args: list[str]) -> str:
    return f"log(2, {args[0]})"


# Complex handlers: ClickHouse function name → callable(list[rendered_arg_strings]) → SQL string
#
# NOTE: toStartOf* functions are NOT here — they are handled by
# PostgresPrinter._visit_to_start_of_call() and inline sub-hour code
# in visit_call(), which intercept before this dict is consulted.
POSTGRES_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    # Type conversions
    "toDate": _make_cast_handler("DATE"),
    "toDateTime": _make_cast_handler("TIMESTAMP"),
    "toString": _make_cast_handler("TEXT"),
    "toInt": _make_cast_handler("BIGINT"),
    "toFloat": _make_cast_handler("DOUBLE PRECISION"),
    "toFloatOrZero": _make_cast_handler("DOUBLE PRECISION"),
    "toIntOrZero": _make_cast_handler("BIGINT"),
    "toBool": _make_cast_handler("BOOLEAN"),
    "toUUID": _make_cast_handler("UUID"),
    # Date extraction
    "toYear": _make_extract_handler("YEAR"),
    "toQuarter": _make_extract_handler("QUARTER"),
    "toMonth": _make_extract_handler("MONTH"),
    "toDayOfMonth": _make_extract_handler("DAY"),
    "toDayOfWeek": _make_extract_handler("ISODOW"),
    "toDayOfYear": _make_extract_handler("DOY"),
    "toHour": _make_extract_handler("HOUR"),
    "toMinute": _make_extract_handler("MINUTE"),
    "toSecond": _make_extract_handler("SECOND"),
    "toUnixTimestamp": _handle_to_unix_timestamp,
    "toYYYYMM": _handle_to_yyyymm,
    # Date truncation (only toMonday — all toStartOf* are handled by visit_call)
    "toMonday": _make_date_trunc_handler("week", cast_to_date=True),
    "toLastDayOfMonth": _handle_to_last_day_of_month,
    # Date generators
    "today": _handle_today,
    "yesterday": _handle_yesterday,
    # Intervals
    "toIntervalSecond": _make_interval_handler("1 second"),
    "toIntervalMinute": _make_interval_handler("1 minute"),
    "toIntervalHour": _make_interval_handler("1 hour"),
    "toIntervalDay": _make_interval_handler("1 day"),
    "toIntervalWeek": _make_interval_handler("1 week"),
    "toIntervalMonth": _make_interval_handler("1 month"),
    "toIntervalQuarter": _make_interval_handler("3 month"),
    "toIntervalYear": _make_interval_handler("1 year"),
    # Date arithmetic
    "addSeconds": _make_date_add_handler("1 second"),
    "addMinutes": _make_date_add_handler("1 minute"),
    "addHours": _make_date_add_handler("1 hour"),
    "addDays": _make_date_add_handler("1 day"),
    "addWeeks": _make_date_add_handler("1 week"),
    "addMonths": _make_date_add_handler("1 month"),
    "addQuarters": _make_date_add_handler("3 month"),
    "addYears": _make_date_add_handler("1 year"),
    "subtractSeconds": _make_date_add_handler("1 second", op="-"),
    "subtractMinutes": _make_date_add_handler("1 minute", op="-"),
    "subtractHours": _make_date_add_handler("1 hour", op="-"),
    "subtractDays": _make_date_add_handler("1 day", op="-"),
    "subtractWeeks": _make_date_add_handler("1 week", op="-"),
    "subtractMonths": _make_date_add_handler("1 month", op="-"),
    "subtractQuarters": _make_date_add_handler("3 month", op="-"),
    "subtractYears": _make_date_add_handler("1 year", op="-"),
    # Date diff
    "dateDiff": _handle_date_diff,
    # Conditional
    "if": _handle_if,
    "multiIf": _handle_multi_if,
    # Null/empty
    "empty": _handle_empty,
    "notEmpty": _handle_not_empty,
    "isNull": _handle_is_null,
    "isNotNull": _handle_is_not_null,
    "assumeNotNull": _handle_noop,
    "toNullable": _handle_noop,
    # JSON with type cast
    "JSONExtractInt": _make_json_cast_handler("INTEGER"),
    "JSONExtractFloat": _make_json_cast_handler("DOUBLE PRECISION"),
    "JSONExtractBool": _make_json_cast_handler("BOOLEAN"),
    # String
    "match": _handle_match,
    "splitByString": _handle_split_by,
    "splitByChar": _handle_split_by,
    "endsWith": _handle_ends_with,
    # Aggregation
    "uniq": _handle_uniq,
    "uniqExact": _handle_uniq,
    # More date extraction
    "toYYYYMMDD": _handle_to_yyyymmdd,
    "toYYYYMMDDhhmmss": _handle_to_yyyymmddhhmmss,
    "toISOWeek": _make_extract_handler("WEEK"),
    "toISOYear": _make_extract_handler("ISOYEAR"),
    # Last day of week
    "toLastDayOfWeek": _handle_to_last_day_of_week,
    # More type conversions
    "toDecimal": _make_cast_handler("DECIMAL"),
    "toDateTime64": _make_cast_handler("TIMESTAMP"),
    "toFloatOrDefault": _make_cast_handler("DOUBLE PRECISION"),
    # More JSON
    "JSONExtractUInt": _make_json_cast_handler("INTEGER"),
    # String
    "replaceOne": _handle_replace_one,
    "replaceRegexpOne": _handle_replace_one,
    # Math
    "e": _handle_e,
    "log2": _handle_log2,
    # Aggregate *If combinators
    "countIf": _handle_count_if,
    "sumIf": _make_if_combinator_handler("sum"),
    "avgIf": _make_if_combinator_handler("avg"),
    "minIf": _make_if_combinator_handler("min"),
    "maxIf": _make_if_combinator_handler("max"),
    "anyIf": _make_if_combinator_handler("MIN"),
    "uniqIf": _handle_uniq_if,
    "uniqExactIf": _handle_uniq_if,
    "groupArrayIf": _make_if_combinator_handler("ARRAY_AGG"),
}


# Case-insensitive lookup maps — keys lowercased for matching against node.name.lower().
# HogQL allows case-insensitive function calls (NOW(), Count(), etc.) but preserves
# the user's original casing in node.name, so the Postgres printer needs these.
POSTGRES_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    k.lower(): v for k, v in POSTGRES_FUNCTION_HANDLERS.items()
}
POSTGRES_FUNCTION_RENAMES_LOWER: dict[str, str] = {k.lower(): v for k, v in POSTGRES_FUNCTION_RENAMES.items()}


# Standard SQL functions that work unchanged in both Postgres and DuckDB.
# Any ClickHouse function NOT in handlers, renames, or this set raises a compile-time error.
POSTGRES_PASSTHROUGH_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Aggregates
        "count",
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
        "pow",
        "power",
        "exp",
        "log",
        "log10",
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
        # Date/time
        "date_trunc",
        # Other
        "md5",
    }
)
