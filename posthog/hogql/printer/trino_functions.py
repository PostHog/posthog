from collections.abc import Callable

from posthog.hogql.transforms.trino.errors import TrinoLoweringError

TRINO_FUNCTION_RENAMES: dict[str, str] = {
    "any": "arbitrary",
    "anyLast": "arbitrary",
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
    "dateTrunc": "date_trunc",
    "substringUTF8": "substring",
    "toLastDayOfMonth": "last_day_of_month",
}


def _require_args(name: str, args: list[str], count: int) -> None:
    if len(args) != count:
        raise _invalid_arguments(name, f"{name} expects exactly {count} arguments in Trino mode.")


def _invalid_arguments(name: str, detail: str) -> TrinoLoweringError:
    return TrinoLoweringError("TRINO_FUNCTION_ARGUMENTS_UNSUPPORTED", name, detail=detail)


def _cast(name: str, trino_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"CAST({args[0]} AS {trino_type})"

    return handler


def _cast_or_default(name: str, trino_type: str, default: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) not in {1, 2}:
            raise _invalid_arguments(name, f"{name} expects one or two arguments in Trino mode.")
        fallback = args[1] if len(args) == 2 else default
        return f"COALESCE(TRY_CAST({args[0]} AS {trino_type}), {fallback})"

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
        raise _invalid_arguments("multiIf", "multiIf expects condition/value pairs and a default in Trino mode.")
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
            raise _invalid_arguments(f"{function}If", f"{function}If expects a value and condition in Trino mode.")
        return f"{function}({', '.join(args[:-1])}) FILTER (WHERE {args[-1]})"

    return handler


def _uniq(args: list[str]) -> str:
    if not args:
        raise _invalid_arguments("uniq", "uniq expects at least one argument in Trino mode.")
    return f"count(DISTINCT {', '.join(args)})"


def _uniq_if(args: list[str]) -> str:
    if len(args) < 2:
        raise _invalid_arguments("uniqIf", "uniqIf expects a value and condition in Trino mode.")
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


def _binary(name: str, operator: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return f"({args[0]} {operator} {args[1]})"

    return handler


def _logical(name: str, operator: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) < 2:
            raise _invalid_arguments(name, f"{name} expects at least two arguments in Trino mode.")
        return f"({f' {operator} '.join(args)})"

    return handler


def _null_check(name: str, negated: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"({args[0]} IS {'NOT ' if negated else ''}NULL)"

    return handler


def _identity(name: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return args[0]

    return handler


def _format_date_time(args: list[str]) -> str:
    _require_args("formatDateTime", args, 2)
    return f"date_format({args[0]}, {args[1]})"


def _position(args: list[str]) -> str:
    _require_args("position", args, 2)
    return f"strpos({args[0]}, {args[1]})"


def _to_monday(args: list[str]) -> str:
    _require_args("toMonday", args, 1)
    return f"date_trunc('week', {args[0]})"


def _to_interval_month(args: list[str]) -> str:
    _require_args("toIntervalMonth", args, 1)
    return f"(CAST({args[0]} AS BIGINT) * INTERVAL '1' MONTH)"


def _current_timestamp(args: list[str]) -> str:
    _require_args("current_timestamp", args, 0)
    return "CURRENT_TIMESTAMP"


TRINO_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "toDate": _cast("toDate", "DATE"),
    "toDateTime": _cast("toDateTime", "TIMESTAMP"),
    "toString": _cast("toString", "VARCHAR"),
    "toInt": _cast("toInt", "BIGINT"),
    "toIntOrZero": _cast_or_default("toIntOrZero", "BIGINT", "0"),
    "toIntOrDefault": _cast_or_default("toIntOrDefault", "BIGINT", "0"),
    "toFloat": _cast("toFloat", "DOUBLE"),
    "toFloatOrZero": _cast_or_default("toFloatOrZero", "DOUBLE", "0e0"),
    "toFloatOrDefault": _cast_or_default("toFloatOrDefault", "DOUBLE", "0e0"),
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
    "equals": _binary("equals", "="),
    "notEquals": _binary("notEquals", "<>"),
    "greater": _binary("greater", ">"),
    "greaterOrEquals": _binary("greaterOrEquals", ">="),
    "less": _binary("less", "<"),
    "lessOrEquals": _binary("lessOrEquals", "<="),
    "plus": _binary("plus", "+"),
    "minus": _binary("minus", "-"),
    "multiply": _binary("multiply", "*"),
    "divide": _binary("divide", "/"),
    "modulo": _binary("modulo", "%"),
    "and": _logical("and", "AND"),
    "or": _logical("or", "OR"),
    "isNull": _null_check("isNull", False),
    "isNotNull": _null_check("isNotNull", True),
    "assumeNotNull": _identity("assumeNotNull"),
    "formatDateTime": _format_date_time,
    "position": _position,
    "toMonday": _to_monday,
    "toIntervalMonth": _to_interval_month,
    "current_timestamp": _current_timestamp,
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
        "json_value",
        "lag",
        "lead",
        "least",
        "length",
        "log10",
        "lower",
        "max",
        "min",
        "nullif",
        "pow",
        "rank",
        "round",
        "row_number",
        "sqrt",
        "sum",
        "substring",
        "upper",
    }
)
