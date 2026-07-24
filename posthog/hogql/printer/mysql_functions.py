from collections.abc import Callable

from posthog.hogql.printer.postgres_functions import (
    _handle_e,
    _handle_empty,
    _handle_if,
    _handle_is_not_null,
    _handle_is_null,
    _handle_multi_if,
    _handle_noop,
    _handle_not_empty,
    _handle_uniq,
)

# Simple 1:1 function name renames (ClickHouse name → MySQL name)
MYSQL_FUNCTION_RENAMES: dict[str, str] = {
    "ifNull": "IFNULL",
    "groupArray": "JSON_ARRAYAGG",
    "fromUnixTimestamp": "FROM_UNIXTIME",
    "replaceAll": "REPLACE",
    "replaceRegexpAll": "REGEXP_REPLACE",
    "JSONLength": "JSON_LENGTH",
    "isValidJSON": "JSON_VALID",
    # ClickHouse formatDateTime and MySQL DATE_FORMAT share the %-based format
    # syntax for the common specifiers. The format string is bound as a query
    # parameter, so its '%' characters never appear in the printed SQL.
    "formatDateTime": "DATE_FORMAT",
    "now": "NOW",
    # MySQL has no arbitrary-value aggregate; MIN is deterministic and already used
    # by the Postgres direct path as the closest portable fallback.
    "any": "MIN",
    "rand": "RAND",
    "toLastDayOfMonth": "LAST_DAY",
    "toDayOfYear": "DAYOFYEAR",
    "toUnixTimestamp": "UNIX_TIMESTAMP",
}


def _make_cast_handler(mysql_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"CAST({args[0]} AS {mysql_type})"

    return handler


def _make_extract_handler(unit: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"EXTRACT({unit} FROM {args[0]})"

    return handler


def _make_interval_handler(unit: str) -> Callable[[list[str]], str]:
    # MySQL has no standalone interval values: `INTERVAL n DAY` is only valid inside
    # date arithmetic. The printer renders `ts + toIntervalDay(n)` as
    # `(ts + INTERVAL (n) DAY)`, which MySQL accepts.
    def handler(args: list[str]) -> str:
        return f"INTERVAL ({args[0]}) {unit}"

    return handler


def _make_date_add_handler(unit: str, fn: str = "DATE_ADD") -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"{fn}({args[0]}, INTERVAL ({args[1]}) {unit})"

    return handler


def _handle_today(args: list[str]) -> str:
    return "CURRENT_DATE"


def _handle_yesterday(args: list[str]) -> str:
    return "(CURRENT_DATE - INTERVAL 1 DAY)"


def _handle_to_day_of_week(args: list[str]) -> str:
    # ClickHouse toDayOfWeek defaults to ISO numbering (Monday = 1); MySQL WEEKDAY is Monday = 0.
    return f"(WEEKDAY({args[0]}) + 1)"


def _handle_to_iso_week(args: list[str]) -> str:
    return f"WEEK({args[0]}, 3)"


def _handle_to_iso_year(args: list[str]) -> str:
    return f"FLOOR(YEARWEEK({args[0]}, 3) / 100)"


def _handle_to_yyyymm(args: list[str]) -> str:
    return f"EXTRACT(YEAR_MONTH FROM {args[0]})"


def _handle_to_yyyymmdd(args: list[str]) -> str:
    return f"(YEAR({args[0]}) * 10000 + MONTH({args[0]}) * 100 + DAY({args[0]}))"


def _handle_to_yyyymmddhhmmss(args: list[str]) -> str:
    arg = args[0]
    return (
        f"((YEAR({arg}) * 10000 + MONTH({arg}) * 100 + DAY({arg})) * 1000000"
        f" + HOUR({arg}) * 10000 + MINUTE({arg}) * 100 + SECOND({arg}))"
    )


def _handle_to_monday(args: list[str]) -> str:
    return f"DATE_SUB(DATE({args[0]}), INTERVAL WEEKDAY({args[0]}) DAY)"


def _handle_to_last_day_of_week(args: list[str]) -> str:
    return f"DATE_ADD(DATE_SUB(DATE({args[0]}), INTERVAL WEEKDAY({args[0]}) DAY), INTERVAL 6 DAY)"


def _handle_match(args: list[str]) -> str:
    # The 'c' flag forces case-sensitive matching, mirroring ClickHouse's match().
    return f"REGEXP_LIKE({args[0]}, {args[1]}, 'c')"


def _handle_starts_with(args: list[str]) -> str:
    return f"(LEFT({args[0]}, CHAR_LENGTH({args[1]})) = {args[1]})"


def _handle_ends_with(args: list[str]) -> str:
    return f"(RIGHT({args[0]}, CHAR_LENGTH({args[1]})) = {args[1]})"


def _handle_position(args: list[str]) -> str:
    # ClickHouse position(haystack, needle[, start]) → MySQL LOCATE(needle, haystack[, start])
    if len(args) == 3:
        return f"LOCATE({args[1]}, {args[0]}, {args[2]})"
    return f"LOCATE({args[1]}, {args[0]})"


def _handle_replace_one(args: list[str]) -> str:
    # Replace only the first occurrence of a plain substring.
    a, b, c = args[0], args[1], args[2]
    return f"IF(LOCATE({b}, {a}) > 0, INSERT({a}, LOCATE({b}, {a}), CHAR_LENGTH({b}), {c}), {a})"


def _handle_replace_regexp_one(args: list[str]) -> str:
    return f"REGEXP_REPLACE({args[0]}, {args[1]}, {args[2]}, 1, 1)"


def _handle_log2(args: list[str]) -> str:
    return f"LOG2({args[0]})"


def _handle_int_div(args: list[str]) -> str:
    return f"({args[0]} DIV {args[1]})"


def _handle_modulo(args: list[str]) -> str:
    return f"MOD({args[0]}, {args[1]})"


def _handle_count_if(args: list[str]) -> str:
    if len(args) == 1:
        return f"COUNT(CASE WHEN {args[0]} THEN 1 END)"
    return f"COUNT(CASE WHEN {args[1]} THEN {args[0]} END)"


def _make_if_combinator_handler(mysql_base_fn: str) -> Callable[[list[str]], str]:
    # MySQL has no FILTER (WHERE ...) clause; CASE-wrap the aggregated expression instead.
    def handler(args: list[str]) -> str:
        agg_args = args[:-1]
        condition = args[-1]
        return f"{mysql_base_fn}(CASE WHEN {condition} THEN {', '.join(agg_args)} END)"

    return handler


def _handle_uniq_if(args: list[str]) -> str:
    agg_args = args[:-1]
    condition = args[-1]
    return f"COUNT(DISTINCT CASE WHEN {condition} THEN {', '.join(agg_args)} END)"


def _json_path_concat(key_args: list[str]) -> str:
    """Build a MySQL JSON path expression from rendered (parameterized) key arguments.

    Keys are bound parameters at this point, so the path is assembled with CONCAT:
    CONCAT('$', '."', key1, '"', '."', key2, '"').
    """
    parts: list[str] = ["'$'"]
    for key in key_args:
        parts.extend(["'.\"'", key, "'\"'"])
    return f"CONCAT({', '.join(parts)})"


def _handle_json_extract_string(args: list[str]) -> str:
    return f"JSON_UNQUOTE(JSON_EXTRACT({args[0]}, {_json_path_concat(args[1:])}))"


def _handle_json_extract_raw(args: list[str]) -> str:
    return f"JSON_EXTRACT({args[0]}, {_json_path_concat(args[1:])})"


def _handle_json_has(args: list[str]) -> str:
    return f"JSON_CONTAINS_PATH({args[0]}, 'one', {_json_path_concat(args[1:])})"


def _make_json_cast_handler(mysql_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"CAST(JSON_UNQUOTE(JSON_EXTRACT({args[0]}, {_json_path_concat(args[1:])})) AS {mysql_type})"

    return handler


def _handle_json_extract_bool(args: list[str]) -> str:
    return f"(JSON_EXTRACT({args[0]}, {_json_path_concat(args[1:])}) = TRUE)"


# Complex handlers: ClickHouse function name → callable(list[rendered_arg_strings]) → SQL string
#
# NOTE: toStartOf* functions and dateDiff/date_trunc are NOT here — they are handled by
# MySQLPrinter._visit_to_start_of_call() / visit_call(), which intercept before this dict
# is consulted (dateDiff needs the unparameterized unit constant).
MYSQL_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    # Type conversions — MySQL CAST never raises; invalid input becomes 0/NULL, which also
    # covers the *OrZero variants faithfully.
    "toDate": _make_cast_handler("DATE"),
    "toDateTime": _make_cast_handler("DATETIME"),
    "toDateTime64": _make_cast_handler("DATETIME"),
    "toString": _make_cast_handler("CHAR"),
    "toInt": _make_cast_handler("SIGNED"),
    "toIntOrZero": _make_cast_handler("SIGNED"),
    "toIntOrDefault": _make_cast_handler("SIGNED"),
    "toFloat": _make_cast_handler("DOUBLE"),
    "toFloatOrZero": _make_cast_handler("DOUBLE"),
    # MySQL backend intentionally drops the default arg — the handler only uses args[0],
    # so this is a plain CAST and the fallback is unsupported.
    "toFloatOrDefault": _make_cast_handler("DOUBLE"),
    "toBool": _make_cast_handler("SIGNED"),
    "toUUID": _make_cast_handler("CHAR"),
    "toDecimal": _make_cast_handler("DECIMAL"),
    # Date extraction
    "toYear": _make_extract_handler("YEAR"),
    "toQuarter": _make_extract_handler("QUARTER"),
    "toMonth": _make_extract_handler("MONTH"),
    "toDayOfMonth": _make_extract_handler("DAY"),
    "toDayOfWeek": _handle_to_day_of_week,
    "toHour": _make_extract_handler("HOUR"),
    "toMinute": _make_extract_handler("MINUTE"),
    "toSecond": _make_extract_handler("SECOND"),
    "toISOWeek": _handle_to_iso_week,
    "toISOYear": _handle_to_iso_year,
    "toYYYYMM": _handle_to_yyyymm,
    "toYYYYMMDD": _handle_to_yyyymmdd,
    "toYYYYMMDDhhmmss": _handle_to_yyyymmddhhmmss,
    # Date truncation (only toMonday — all toStartOf* are handled by visit_call)
    "toMonday": _handle_to_monday,
    "toLastDayOfWeek": _handle_to_last_day_of_week,
    # Date generators
    "today": _handle_today,
    "yesterday": _handle_yesterday,
    # Intervals
    "toIntervalSecond": _make_interval_handler("SECOND"),
    "toIntervalMinute": _make_interval_handler("MINUTE"),
    "toIntervalHour": _make_interval_handler("HOUR"),
    "toIntervalDay": _make_interval_handler("DAY"),
    "toIntervalWeek": _make_interval_handler("WEEK"),
    "toIntervalMonth": _make_interval_handler("MONTH"),
    "toIntervalQuarter": _make_interval_handler("QUARTER"),
    "toIntervalYear": _make_interval_handler("YEAR"),
    # Date arithmetic
    "addSeconds": _make_date_add_handler("SECOND"),
    "addMinutes": _make_date_add_handler("MINUTE"),
    "addHours": _make_date_add_handler("HOUR"),
    "addDays": _make_date_add_handler("DAY"),
    "addWeeks": _make_date_add_handler("WEEK"),
    "addMonths": _make_date_add_handler("MONTH"),
    "addQuarters": _make_date_add_handler("QUARTER"),
    "addYears": _make_date_add_handler("YEAR"),
    "subtractSeconds": _make_date_add_handler("SECOND", fn="DATE_SUB"),
    "subtractMinutes": _make_date_add_handler("MINUTE", fn="DATE_SUB"),
    "subtractHours": _make_date_add_handler("HOUR", fn="DATE_SUB"),
    "subtractDays": _make_date_add_handler("DAY", fn="DATE_SUB"),
    "subtractWeeks": _make_date_add_handler("WEEK", fn="DATE_SUB"),
    "subtractMonths": _make_date_add_handler("MONTH", fn="DATE_SUB"),
    "subtractQuarters": _make_date_add_handler("QUARTER", fn="DATE_SUB"),
    "subtractYears": _make_date_add_handler("YEAR", fn="DATE_SUB"),
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
    # JSON
    "JSONExtractString": _handle_json_extract_string,
    "JSONExtractRaw": _handle_json_extract_raw,
    "JSONExtractArrayRaw": _handle_json_extract_raw,
    "JSONExtractInt": _make_json_cast_handler("SIGNED"),
    "JSONExtractUInt": _make_json_cast_handler("UNSIGNED"),
    "JSONExtractFloat": _make_json_cast_handler("DOUBLE"),
    "JSONExtractBool": _handle_json_extract_bool,
    "JSONHas": _handle_json_has,
    # String
    "match": _handle_match,
    "startsWith": _handle_starts_with,
    "endsWith": _handle_ends_with,
    "position": _handle_position,
    "replaceOne": _handle_replace_one,
    "replaceRegexpOne": _handle_replace_regexp_one,
    # Aggregation
    "uniq": _handle_uniq,
    "uniqExact": _handle_uniq,
    # Math
    "e": _handle_e,
    "log2": _handle_log2,
    "intDiv": _handle_int_div,
    "modulo": _handle_modulo,
    # Aggregate *If combinators
    "countIf": _handle_count_if,
    "sumIf": _make_if_combinator_handler("SUM"),
    "avgIf": _make_if_combinator_handler("AVG"),
    "minIf": _make_if_combinator_handler("MIN"),
    "maxIf": _make_if_combinator_handler("MAX"),
    # Keep the same deterministic fallback as any().
    "anyIf": _make_if_combinator_handler("MIN"),
    "uniqIf": _handle_uniq_if,
    "uniqExactIf": _handle_uniq_if,
}


# Case-insensitive lookup maps — keys lowercased for matching against node.name.lower().
MYSQL_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    k.lower(): v for k, v in MYSQL_FUNCTION_HANDLERS.items()
}
MYSQL_FUNCTION_RENAMES_LOWER: dict[str, str] = {k.lower(): v for k, v in MYSQL_FUNCTION_RENAMES.items()}


# Standard SQL functions that work unchanged in MySQL 8.
# Any ClickHouse function NOT in handlers, renames, or this set raises a compile-time error.
MYSQL_PASSTHROUGH_FUNCTIONS: frozenset[str] = frozenset(
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
        "reverse",
        "replace",
        "lpad",
        "rpad",
        "repeat",
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
        # Other
        "md5",
    }
)
