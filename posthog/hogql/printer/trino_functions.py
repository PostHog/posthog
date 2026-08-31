from collections.abc import Callable

from posthog.hogql.errors import QueryError


def _cast(type_name: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"CAST({args[0]} AS {type_name})"

    return handler


def _try_cast_or_default(type_name: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) not in {1, 2}:
            raise QueryError(f"Conversion to {type_name} expects one value and an optional default")
        default = args[1] if len(args) == 2 else "0"
        return f"COALESCE(TRY_CAST({args[0]} AS {type_name}), CAST({default} AS {type_name}))"

    return handler


def _extract(unit: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"EXTRACT({unit} FROM {args[0]})"

    return handler


def _aggregate_if(function_name: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"{function_name}({', '.join(args[:-1])}) FILTER (WHERE {args[-1]})"

    return handler


def _if(args: list[str]) -> str:
    return f"CASE WHEN {args[0]} THEN {args[1]} ELSE {args[2]} END"


def _multi_if(args: list[str]) -> str:
    parts = ["CASE"]
    for index in range(0, len(args) - 1, 2):
        parts.append(f"WHEN {args[index]} THEN {args[index + 1]}")
    parts.append(f"ELSE {args[-1]} END")
    return " ".join(parts)


def _count_if(args: list[str]) -> str:
    if len(args) == 1:
        return f"count(*) FILTER (WHERE {args[0]})"
    return f"count({args[0]}) FILTER (WHERE {args[1]})"


def _uniq(args: list[str]) -> str:
    distinct_value = args[0] if len(args) == 1 else f"ROW({', '.join(args)})"
    return f"count(DISTINCT {distinct_value})"


def _uniq_if(args: list[str]) -> str:
    values = args[:-1]
    distinct_value = values[0] if len(values) == 1 else f"ROW({', '.join(values)})"
    return f"count(DISTINCT {distinct_value}) FILTER (WHERE {args[-1]})"


def _date_diff(args: list[str]) -> str:
    return f"date_diff({args[0]}, {args[1]}, {args[2]})"


def _date_add(args: list[str]) -> str:
    if len(args) == 2:
        return f"({args[0]} + {args[1]})"
    return f"date_add({args[0]}, {args[1]}, {args[2]})"


def _date_sub(args: list[str]) -> str:
    return f"date_add({args[0]}, -({args[1]}), {args[2]})"


def _date_trunc(args: list[str]) -> str:
    value = args[1]
    if len(args) == 3:
        value = f"at_timezone(with_timezone(CAST({value} AS TIMESTAMP), 'UTC'), {args[2]})"
    return f"date_trunc({args[0]}, {value})"


def _array_map(args: list[str]) -> str:
    if len(args) != 2:
        raise QueryError("arrayMap with multiple arrays is not supported in the Trino dialect")
    return f"transform({args[1]}, {args[0]})"


def _array_filter(args: list[str]) -> str:
    if len(args) != 2:
        raise QueryError("arrayFilter with multiple arrays is not supported in the Trino dialect")
    return f"filter({args[1]}, {args[0]})"


def _split_by_string(args: list[str]) -> str:
    return f"split({args[1]}, {args[0]})"


def _binary_operator(operator: str, *, cast_left_to_double: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        left = f"CAST({args[0]} AS DOUBLE)" if cast_left_to_double else args[0]
        return f"({left} {operator} {args[1]})"

    return handler


def _logical_operator(operator: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"({f' {operator} '.join(args)})"

    return handler


def _group_uniq_array(args: list[str]) -> str:
    return f"array_distinct(array_agg({args[0]}))"


def _group_uniq_array_if(args: list[str]) -> str:
    return f"array_distinct(array_agg({args[0]}) FILTER (WHERE {args[1]}))"


def _arg_extreme_if(function_name: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        return f"{function_name}({args[0]}, {args[1]}) FILTER (WHERE {args[2]})"

    return handler


def _md5(args: list[str]) -> str:
    return f"to_hex(md5(to_utf8(CAST({args[0]} AS VARCHAR))))"


def _int_div(args: list[str]) -> str:
    return f"CAST(floor(CAST({args[0]} AS DOUBLE) / {args[1]}) AS BIGINT)"


def _to_datetime(args: list[str]) -> str:
    timestamp = f"CAST({args[0]} AS TIMESTAMP)"
    return timestamp if len(args) == 1 else f"with_timezone({timestamp}, {args[1]})"


def _to_timezone(args: list[str]) -> str:
    return f"at_timezone(with_timezone(CAST({args[0]} AS TIMESTAMP), 'UTC'), {args[1]})"


def _interval(unit: str, multiplier: int = 1) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        amount = args[0] if multiplier == 1 else f"({args[0]} * {multiplier})"
        return f"({amount} * INTERVAL '1' {unit})"

    return handler


def _add_date(unit: str, multiplier: int = 1, subtract: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        amount = f"({args[1]} * {multiplier})" if multiplier != 1 else args[1]
        if subtract:
            amount = f"-({amount})"
        return f"date_add('{unit}', {amount}, {args[0]})"

    return handler


TRINO_FUNCTION_RENAMES: dict[str, str] = {
    "ifNull": "coalesce",
    "groupArray": "array_agg",
    "fromUnixTimestamp": "from_unixtime",
    "replaceAll": "replace",
    "replaceRegexpAll": "regexp_replace",
    "arrayStringConcat": "array_join",
    "JSONLength": "json_array_length",
    "toTypeName": "typeof",
    "formatDateTime": "date_format",
    "formatReadableTimeDelta": "human_readable_seconds",
    "now": "now",
    "any": "arbitrary",
    "anyLast": "arbitrary",
    "startsWith": "starts_with",
    "endsWith": "ends_with",
    "rand": "random",
    "argMax": "max_by",
    "argMin": "min_by",
    "arrayConcat": "concat",
    "arrayDistinct": "array_distinct",
    "arrayFlatten": "flatten",
    "arrayMin": "array_min",
    "arraySort": "array_sort",
    "dateTrunc": "date_trunc",
    "hasAny": "arrays_overlap",
    "mapFromArrays": "map",
    "mapUpdate": "map_concat",
    "substringUTF8": "substring",
    "parseDateTime": "date_parse",
}


TRINO_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "toDate": _cast("DATE"),
    "_toDate": _cast("DATE"),
    "toDateTime": _to_datetime,
    "toString": _cast("VARCHAR"),
    "toInt": _cast("BIGINT"),
    "toInt8": _cast("BIGINT"),
    "toInt16": _cast("BIGINT"),
    "_toInt16": _cast("BIGINT"),
    "toInt32": _cast("BIGINT"),
    "toInt64": _cast("BIGINT"),
    "toUInt": _cast("BIGINT"),
    "toUInt8": _cast("BIGINT"),
    "toUInt16": _cast("BIGINT"),
    "toUInt32": _cast("BIGINT"),
    "toUInt64": _cast("DECIMAL(20, 0)"),
    "toFloat": _cast("DOUBLE"),
    "toFloat32": _cast("REAL"),
    "toFloat64": _cast("DOUBLE"),
    "toFloatOrZero": _try_cast_or_default("DOUBLE"),
    "toFloatOrDefault": _try_cast_or_default("DOUBLE"),
    "toIntOrZero": _try_cast_or_default("BIGINT"),
    "toIntOrDefault": _try_cast_or_default("BIGINT"),
    "toBool": _cast("BOOLEAN"),
    "toUUID": _cast("UUID"),
    "toDecimal": _cast("DECIMAL"),
    "toDateTime64": _cast("TIMESTAMP"),
    "toUnixTimestamp": lambda args: f"CAST(to_unixtime({args[0]}) AS BIGINT)",
    "toYear": _extract("YEAR"),
    "toQuarter": _extract("QUARTER"),
    "toMonth": _extract("MONTH"),
    "toDayOfMonth": _extract("DAY"),
    "toDayOfWeek": _extract("DAY_OF_WEEK"),
    "toDayOfYear": _extract("DAY_OF_YEAR"),
    "toHour": _extract("HOUR"),
    "toMinute": _extract("MINUTE"),
    "toSecond": _extract("SECOND"),
    "toISOWeek": lambda args: f"week({args[0]})",
    "toISOYear": lambda args: f"year_of_week({args[0]})",
    "toYYYYMM": lambda args: f"CAST(date_format({args[0]}, '%Y%m') AS INTEGER)",
    "toYYYYMMDD": lambda args: f"CAST(date_format({args[0]}, '%Y%m%d') AS INTEGER)",
    "toYYYYMMDDhhmmss": lambda args: f"CAST(date_format({args[0]}, '%Y%m%d%H%i%s') AS BIGINT)",
    "toMonday": lambda args: f"CAST(date_trunc('week', {args[0]}) AS DATE)",
    "toLastDayOfMonth": lambda args: f"last_day_of_month({args[0]})",
    "toLastDayOfWeek": lambda args: f"CAST(date_add('day', 6, date_trunc('week', {args[0]})) AS DATE)",
    "today": lambda args: "CURRENT_DATE",
    "yesterday": lambda args: "date_add('day', -1, CURRENT_DATE)",
    "toIntervalSecond": _interval("SECOND"),
    "toIntervalMinute": _interval("MINUTE"),
    "toIntervalHour": _interval("HOUR"),
    "toIntervalDay": _interval("DAY"),
    "toIntervalWeek": _interval("DAY", 7),
    "toIntervalMonth": _interval("MONTH"),
    "toIntervalQuarter": _interval("MONTH", 3),
    "toIntervalYear": _interval("YEAR"),
    "addSeconds": _add_date("second"),
    "addMinutes": _add_date("minute"),
    "addHours": _add_date("hour"),
    "addDays": _add_date("day"),
    "addWeeks": _add_date("week"),
    "addMonths": _add_date("month"),
    "addQuarters": _add_date("month", 3),
    "addYears": _add_date("year"),
    "subtractSeconds": _add_date("second", subtract=True),
    "subtractMinutes": _add_date("minute", subtract=True),
    "subtractHours": _add_date("hour", subtract=True),
    "subtractDays": _add_date("day", subtract=True),
    "subtractWeeks": _add_date("week", subtract=True),
    "subtractMonths": _add_date("month", subtract=True),
    "subtractQuarters": _add_date("month", 3, subtract=True),
    "subtractYears": _add_date("year", subtract=True),
    "if": _if,
    "multiIf": _multi_if,
    "countIf": _count_if,
    "sumIf": _aggregate_if("sum"),
    "avgIf": _aggregate_if("avg"),
    "minIf": _aggregate_if("min"),
    "maxIf": _aggregate_if("max"),
    "anyIf": _aggregate_if("arbitrary"),
    "groupArrayIf": _aggregate_if("array_agg"),
    "groupUniqArray": _group_uniq_array,
    "groupUniqArrayIf": _group_uniq_array_if,
    "argMaxIf": _arg_extreme_if("max_by"),
    "argMinIf": _arg_extreme_if("min_by"),
    "uniq": _uniq,
    "uniqExact": _uniq,
    "uniqIf": _uniq_if,
    "uniqExactIf": _uniq_if,
    "dateDiff": _date_diff,
    "date_diff": _date_diff,
    "dateAdd": _date_add,
    "dateSub": _date_sub,
    "dateTrunc": _date_trunc,
    "date_trunc": _date_trunc,
    "empty": lambda args: f"(COALESCE(length({args[0]}), 0) = 0)",
    "notEmpty": lambda args: f"(COALESCE(length({args[0]}), 0) > 0)",
    "isNull": lambda args: f"({args[0]} IS NULL)",
    "isNotNull": lambda args: f"({args[0]} IS NOT NULL)",
    "assumeNotNull": lambda args: args[0],
    "toNullable": lambda args: args[0],
    "match": lambda args: f"regexp_like({args[0]}, {args[1]})",
    "extract": lambda args: f"regexp_extract({args[0]}, {args[1]})",
    "extractAll": lambda args: f"regexp_extract_all({args[0]}, {args[1]})",
    "splitByString": _split_by_string,
    "splitByChar": _split_by_string,
    "arrayMap": _array_map,
    "arrayFilter": _array_filter,
    "arrayFirst": lambda args: f"element_at(filter({args[1]}, {args[0]}), 1)",
    "has": lambda args: f"contains({args[0]}, {args[1]})",
    "arrayElement": lambda args: f"element_at({args[0]}, {args[1]})",
    "concat": lambda args: f"concat({', '.join(args)})",
    "position": lambda args: f"strpos({args[0]}, {args[1]})",
    "e": lambda args: "exp(1)",
    "tuple": lambda args: f"ROW({', '.join(args)})",
    "not": lambda args: f"(NOT {args[0]})",
    "and": _logical_operator("AND"),
    "or": _logical_operator("OR"),
    "plus": _binary_operator("+"),
    "minus": _binary_operator("-"),
    "multiply": _binary_operator("*"),
    "multiplyDecimal": _binary_operator("*"),
    "divide": _binary_operator("/", cast_left_to_double=True),
    "divideDecimal": _binary_operator("/"),
    "intDiv": _int_div,
    "md5": _md5,
    "current_timestamp": lambda args: "CURRENT_TIMESTAMP",
    "toTimeZone": _to_timezone,
    "toJSONString": lambda args: f"json_format(CAST({args[0]} AS JSON))",
    "medianIf": lambda args: f"approx_percentile({args[0]}, 0.5) FILTER (WHERE {args[1]})",
}

TRINO_FUNCTION_HANDLERS_LOWER = {name.lower(): handler for name, handler in TRINO_FUNCTION_HANDLERS.items()}
TRINO_FUNCTION_RENAMES_LOWER = {name.lower(): target for name, target in TRINO_FUNCTION_RENAMES.items()}

TRINO_PASSTHROUGH_FUNCTIONS: frozenset[str] = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "abs",
        "floor",
        "ceil",
        "round",
        "sqrt",
        "pow",
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
        "lower",
        "upper",
        "trim",
        "ltrim",
        "rtrim",
        "substring",
        "length",
        "reverse",
        "replace",
        "lpad",
        "rpad",
        "repeat",
        "log2",
        "log10",
        "coalesce",
        "nullif",
        "date_trunc",
    }
)
