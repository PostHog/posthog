from collections.abc import Callable

from posthog.hogql.errors import QueryError

TRINO_FUNCTION_RENAMES: dict[str, str] = {
    "ifNull": "coalesce",
    "groupArray": "array_agg",
    "JSONExtractString": "json_extract_scalar",
    "JSONExtractRaw": "json_extract",
    "JSONExtractArrayRaw": "json_extract",
    "fromUnixTimestamp": "from_unixtime",
    "replaceAll": "replace",
    "replaceRegexpAll": "regexp_replace",
    "arrayStringConcat": "array_join",
    "JSONLength": "json_array_length",
    "toTypeName": "typeof",
    "now": "now",
    "startsWith": "starts_with",
    "rand": "random",
}


def _require_args(name: str, args: list[str], count: int) -> None:
    if len(args) != count:
        raise QueryError(f"{name} expects exactly {count} arguments in Trino mode.")


def _cast(name: str, trino_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"CAST({args[0]} AS {trino_type})"

    return handler


def _extract(name: str, unit: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"EXTRACT({unit} FROM {args[0]})"

    return handler


def _if(args: list[str]) -> str:
    _require_args("if", args, 3)
    return f"CASE WHEN {args[0]} THEN {args[1]} ELSE {args[2]} END"


def _multi_if(args: list[str]) -> str:
    if len(args) < 3 or len(args) % 2 == 0:
        raise QueryError("multiIf expects condition/value pairs and a default in Trino mode.")
    parts = ["CASE"]
    for index in range(0, len(args) - 1, 2):
        parts.append(f"WHEN {args[index]} THEN {args[index + 1]}")
    parts.append(f"ELSE {args[-1]} END")
    return " ".join(parts)


def _count_if(args: list[str]) -> str:
    _require_args("countIf", args, 1)
    return f"count(*) FILTER (WHERE {args[0]})"


def _aggregate_if(function: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) < 2:
            raise QueryError(f"{function}If expects a value and condition in Trino mode.")
        return f"{function}({', '.join(args[:-1])}) FILTER (WHERE {args[-1]})"

    return handler


def _uniq(args: list[str]) -> str:
    if not args:
        raise QueryError("uniq expects at least one argument in Trino mode.")
    return f"count(DISTINCT {', '.join(args)})"


def _uniq_if(args: list[str]) -> str:
    if len(args) < 2:
        raise QueryError("uniqIf expects a value and condition in Trino mode.")
    return f"count(DISTINCT {', '.join(args[:-1])}) FILTER (WHERE {args[-1]})"


def _date_diff(args: list[str]) -> str:
    _require_args("dateDiff", args, 3)
    return f"date_diff({args[0]}, {args[1]}, {args[2]})"


def _date_add(unit: str, sign: int = 1) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args("date arithmetic", args, 2)
        amount = args[1] if sign == 1 else f"-({args[1]})"
        return f"date_add('{unit}', {amount}, {args[0]})"

    return handler


def _interval(unit: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args("interval", args, 1)
        return f"parse_duration(CAST({args[0]} AS VARCHAR) || ' {unit}')"

    return handler


def _today(args: list[str]) -> str:
    _require_args("today", args, 0)
    return "CURRENT_DATE"


def _yesterday(args: list[str]) -> str:
    _require_args("yesterday", args, 0)
    return "CURRENT_DATE - INTERVAL '1' DAY"


def _to_unix_timestamp(args: list[str]) -> str:
    _require_args("toUnixTimestamp", args, 1)
    return f"CAST(to_unixtime({args[0]}) AS BIGINT)"


def _empty(args: list[str]) -> str:
    _require_args("empty", args, 1)
    return f"({args[0]} IS NULL OR cardinality({args[0]}) = 0)"


def _not_empty(args: list[str]) -> str:
    _require_args("notEmpty", args, 1)
    return f"({args[0]} IS NOT NULL AND cardinality({args[0]}) > 0)"


TRINO_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "toDate": _cast("toDate", "DATE"),
    "toDateTime": _cast("toDateTime", "TIMESTAMP"),
    "toString": _cast("toString", "VARCHAR"),
    "toInt": _cast("toInt", "BIGINT"),
    "toIntOrZero": _cast("toIntOrZero", "BIGINT"),
    "toIntOrDefault": _cast("toIntOrDefault", "BIGINT"),
    "toFloat": _cast("toFloat", "DOUBLE"),
    "toFloatOrZero": _cast("toFloatOrZero", "DOUBLE"),
    "toFloatOrDefault": _cast("toFloatOrDefault", "DOUBLE"),
    "toBool": _cast("toBool", "BOOLEAN"),
    "toUUID": _cast("toUUID", "UUID"),
    "toYear": _extract("toYear", "YEAR"),
    "toQuarter": _extract("toQuarter", "QUARTER"),
    "toMonth": _extract("toMonth", "MONTH"),
    "toDayOfMonth": _extract("toDayOfMonth", "DAY"),
    "toDayOfWeek": _extract("toDayOfWeek", "DAY_OF_WEEK"),
    "toDayOfYear": _extract("toDayOfYear", "DAY_OF_YEAR"),
    "toHour": _extract("toHour", "HOUR"),
    "toMinute": _extract("toMinute", "MINUTE"),
    "toSecond": _extract("toSecond", "SECOND"),
    "toUnixTimestamp": _to_unix_timestamp,
    "if": _if,
    "multiIf": _multi_if,
    "countIf": _count_if,
    "sumIf": _aggregate_if("sum"),
    "minIf": _aggregate_if("min"),
    "maxIf": _aggregate_if("max"),
    "avgIf": _aggregate_if("avg"),
    "uniq": _uniq,
    "uniqExact": _uniq,
    "uniqIf": _uniq_if,
    "uniqExactIf": _uniq_if,
    "dateDiff": _date_diff,
    "addSeconds": _date_add("second"),
    "addMinutes": _date_add("minute"),
    "addHours": _date_add("hour"),
    "addDays": _date_add("day"),
    "addWeeks": _date_add("week"),
    "addMonths": _date_add("month"),
    "addQuarters": _date_add("quarter"),
    "addYears": _date_add("year"),
    "subtractSeconds": _date_add("second", -1),
    "subtractMinutes": _date_add("minute", -1),
    "subtractHours": _date_add("hour", -1),
    "subtractDays": _date_add("day", -1),
    "subtractWeeks": _date_add("week", -1),
    "subtractMonths": _date_add("month", -1),
    "subtractQuarters": _date_add("quarter", -1),
    "subtractYears": _date_add("year", -1),
    "toIntervalSecond": _interval("seconds"),
    "toIntervalMinute": _interval("minutes"),
    "toIntervalHour": _interval("hours"),
    "toIntervalDay": _interval("days"),
    "toIntervalWeek": _interval("weeks"),
    "today": _today,
    "yesterday": _yesterday,
    "empty": _empty,
    "notEmpty": _not_empty,
}

TRINO_FUNCTION_RENAMES_LOWER = {name.lower(): target for name, target in TRINO_FUNCTION_RENAMES.items()}
TRINO_FUNCTION_HANDLERS_LOWER = {name.lower(): handler for name, handler in TRINO_FUNCTION_HANDLERS.items()}

TRINO_PASSTHROUGH_FUNCTIONS = frozenset(
    {
        "abs",
        "array_agg",
        "avg",
        "cardinality",
        "ceil",
        "coalesce",
        "concat",
        "count",
        "date_trunc",
        "dense_rank",
        "exp",
        "floor",
        "greatest",
        "lag",
        "lead",
        "least",
        "length",
        "lower",
        "max",
        "md5",
        "min",
        "nullif",
        "position",
        "pow",
        "rank",
        "round",
        "row_number",
        "sqrt",
        "sum",
        "upper",
    }
)
