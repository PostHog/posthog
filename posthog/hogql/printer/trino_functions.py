from collections.abc import Callable
from math import factorial

from posthog.hogql.transforms.trino.errors import TrinoLoweringError

TRINO_AGGREGATE_COMBINATORS = {
    f"{base}{array}{empty}{condition}".lower(): (base, array, empty, bool(condition))
    for base in ("avg", "sum", "min", "max", "count", "countDistinct", "median")
    for array in ("", "Array", "ForEach", "Map", "ArgMin", "ArgMax")
    for empty in ("", "OrDefault", "OrNull")
    for condition in ("", "If")
    if array or empty
}
TRINO_EXACT_QUANTILES = frozenset(
    f"{base}{condition}"
    for base in ("quantileexact", "medianexact", "medianexactlow", "medianexacthigh")
    for condition in ("", "if")
)
TRINO_EXACT_WEIGHTED_MEDIANS = frozenset({"medianexactweighted", "medianexactweightedif"})
TRINO_QUANTILES = frozenset({"quantiles", "quantilesif"})
TRINO_STATISTICAL_AGGREGATES = frozenset(
    f"{base}{condition}"
    for base in ("skewpop", "skewsamp", "kurtpop", "kurtsamp", "simplelinearregression")
    for condition in ("", "if")
)
TRINO_UNIQUE_ARRAY_AGGREGATES = frozenset({"groupuniqarrayarray", "groupuniqarrayarrayif"})
TRINO_MOVING_ARRAY_AGGREGATES = frozenset(
    {"grouparraymovingsum", "grouparraymovingsumif", "grouparraymovingavg", "grouparraymovingavgif"}
)
TRINO_DELTA_AGGREGATES = frozenset({"deltasum", "deltasumif"})
TRINO_ARRAY_INSERT_AGGREGATES = frozenset({"grouparrayinsertat", "grouparrayinsertatif"})
TRINO_INTERSECTION_AGGREGATES = frozenset(
    {"maxintersections", "maxintersectionsif", "maxintersectionsposition", "maxintersectionspositionif"}
)
TRINO_WINDOW_ONLY_FUNCTIONS = frozenset({"laginframe", "leadinframe"})
TRINO_TUPLE_OPERATORS = {
    "tupleplus": "+",
    "tupleminus": "-",
    "tuplemultiply": "*",
    "tupledivide": "/",
    "tuplenegate": "-",
    "tuplemultiplybynumber": "*",
    "tupledividebynumber": "/",
    "tuplehammingdistance": "!=",
}
TRINO_VECTOR_REWRITES = frozenset(
    {"lpnorm", "lpdistance", "l1normalize", "l2normalize", "linfnormalize", "lpnormalize"}
)

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
    "now": "now",
    "startsWith": "starts_with",
    "rand": "random",
    "dateTrunc": "date_trunc",
    "substringUTF8": "substring",
    "lowerUTF8": "lower",
    "upperUTF8": "upper",
    "encodeURLComponent": "url_encode",
    "encodeURLFormComponent": "url_encode",
    "lengthUTF8": "length",
    "toLastDayOfMonth": "last_day_of_month",
    "mapFromArrays": "map",
    "mapUpdate": "map_concat",
    "log": "ln",
    "decodeURLComponent": "url_decode",
    "decodeURLFormComponent": "url_decode",
    "trimLeft": "ltrim",
    "trimRight": "rtrim",
    "leftPad": "lpad",
    "indexOf": "array_position",
    "TRUNC": "truncate",
    "JSONArrayLength": "json_array_length",
    "age": "date_diff",
    "arrayReverse": "reverse",
    "cosineDistance": "cosine_distance",
    "dotProduct": "dot_product",
    "L2Distance": "euclidean_distance",
    "bitAnd": "bitwise_and",
    "bitOr": "bitwise_or",
    "bitXor": "bitwise_xor",
    "corr": "corr",
    "isFinite": "is_finite",
    "isInfinite": "is_infinite",
    "isNaN": "is_nan",
    "mapKeys": "map_keys",
    "mapValues": "map_values",
    "reverseUTF8": "reverse",
    "split_part": "split_part",
    "stddevPop": "stddev_pop",
    "stddevSamp": "stddev_samp",
    "translate": "translate",
    "translateUTF8": "translate",
    "btrim": "trim",
    "varPop": "var_pop",
    "varSamp": "var_samp",
    "covarPop": "covar_pop",
    "covarSamp": "covar_samp",
    "width_bucket": "width_bucket",
    "hasSubstr": "contains_sequence",
    "groupBitAnd": "bitwise_and_agg",
    "groupBitOr": "bitwise_or_agg",
    "groupBitXor": "bitwise_xor_agg",
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
        fallback = f"CAST({fallback} AS {trino_type})"
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


def _case_with_expression(args: list[str]) -> str:
    if len(args) < 4 or len(args) % 2 != 0:
        raise _invalid_arguments("caseWithExpression", "CASE expects a value, match/result pairs, and a default.")
    parts = [f"CASE {args[0]}"]
    parts.extend(f"WHEN {args[index]} THEN {args[index + 1]}" for index in range(1, len(args) - 1, 2))
    parts.append(f"ELSE {args[-1]} END")
    return " ".join(parts)


def _count_if(args: list[str]) -> str:
    if len(args) == 1:
        return f"count(*) FILTER (WHERE {args[0]})"
    if len(args) == 2:
        return f"count({args[0]}) FILTER (WHERE {args[1]})"
    raise _invalid_arguments("countIf", "countIf expects one or two arguments in Trino mode.")


def _aggregate_if(function: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) < 2:
            raise _invalid_arguments(f"{function}If", f"{function}If expects a value and condition in Trino mode.")
        return f"{function}({', '.join(args[:-1])}) FILTER (WHERE {args[-1]})"

    return handler


def _has_token(name: str, case_insensitive: bool, null_on_invalid: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        raw_haystack = "__hogql_token_args[1]"
        raw_needle = "__hogql_token_args[2]"
        haystack = raw_haystack
        needle = raw_needle
        if case_insensitive:
            alphabet = "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'"
            haystack = f"translate({haystack}, {alphabet})"
            needle = f"translate({needle}, {alphabet})"
        escaped = f"regexp_replace({needle}, '([\\\\|()^$.\\-\\[\\]?*+{{:\\x00])', '\\\\$1')"
        token_character = r"A-Za-z0-9\P{ASCII}"
        valid = f"{needle} = '' OR regexp_like({needle}, '^[{token_character}]+$')"
        pattern = f"concat('(?:^|[^{token_character}])', {escaped}, '(?:$|[^{token_character}])')"
        result = f"IF({needle} = '', false, regexp_like({haystack}, {pattern}))"
        invalid = "NULL" if null_on_invalid else f"fail('{name} requires one token as its second argument')"
        result = f"IF({valid}, {result}, {invalid})"
        result = f"IF({raw_haystack} IS NULL OR {raw_needle} IS NULL, NULL, {result})"
        return f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_token_args -> {result}), 1)"

    return handler


def _format_readable(name: str, base: int, units: tuple[str, ...]) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        value = "__hogql_readable"
        unit_index = (
            f"IF(is_nan({value}), BIGINT '0', IF(is_infinite({value}), BIGINT '{len(units) - 1}', "
            f"IF(abs({value}) < {base}, BIGINT '0', "
            f"least(CAST(floor(ln(abs({value})) / ln({base}e0)) AS BIGINT), {len(units) - 1}))))"
        )
        unit = f"element_at(ARRAY[{', '.join(repr(unit) for unit in units)}], __hogql_unit_index + 1)"
        suffix = f"IF({unit} = '', '', concat(' ', {unit}))"
        finite = f"concat(format('%.2f', {value} / power({base}e0, __hogql_unit_index)), {suffix})"
        nan = "'nan'" if units[0] == "" else f"'nan {units[0]}'"
        infinity = f"concat(IF({value} < 0, '-inf', 'inf'), IF('{units[-1]}' = '', '', ' {units[-1]}'))"
        result = f"IF(is_nan({value}), {nan}, IF(is_infinite({value}), {infinity}, {finite}))"
        return (
            f"element_at(transform(ARRAY[CAST({args[0]} AS DOUBLE)], {value} -> "
            f"element_at(transform(ARRAY[{unit_index}], __hogql_unit_index -> {result}), 1)), 1)"
        )

    return handler


def _uniq(args: list[str]) -> str:
    if not args:
        raise _invalid_arguments("uniq", "uniq expects at least one argument in Trino mode.")
    value = args[0] if len(args) == 1 else f"ROW({', '.join(args)})"
    return f"count(DISTINCT {value})"


def _uniq_if(args: list[str]) -> str:
    if len(args) < 2:
        raise _invalid_arguments("uniqIf", "uniqIf expects a value and condition in Trino mode.")
    values = args[:-1]
    value = values[0] if len(values) == 1 else f"ROW({', '.join(values)})"
    return f"count(DISTINCT {value}) FILTER (WHERE {args[-1]})"


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
        return f"(CAST({args[0]} AS BIGINT) * INTERVAL '1' {unit.rstrip('s').upper()})"

    return handler


def _today(args: list[str]) -> str:
    _require_args("today", args, 0)
    return "CURRENT_DATE"


def _yesterday(args: list[str]) -> str:
    _require_args("yesterday", args, 0)
    return "date_add('day', -1, CURRENT_DATE)"


def _to_unix_timestamp(args: list[str]) -> str:
    _require_args("toUnixTimestamp", args, 1)
    return f"CAST(to_unixtime({args[0]}) AS BIGINT)"


def _binary(name: str, operator: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return f"({args[0]} {operator} {args[1]})"

    return handler


def _divide(args: list[str]) -> str:
    _require_args("divide", args, 2)
    return f"(CAST({args[0]} AS DOUBLE) / CAST({args[1]} AS DOUBLE))"


def _divide_decimal(args: list[str]) -> str:
    _require_args("divideDecimal", args, 2)
    return f"({args[0]} / {args[1]})"


def _not(args: list[str]) -> str:
    _require_args("not", args, 1)
    return f"(NOT {args[0]})"


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


def _constant(name: str, value: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return value

    return handler


def _array_string_concat(args: list[str]) -> str:
    if len(args) not in {1, 2}:
        raise _invalid_arguments("arrayStringConcat", "arrayStringConcat expects an array and optional separator.")
    separator = args[1] if len(args) == 2 else "''"
    return f"array_join({args[0]}, {separator})"


def _ends_with(args: list[str]) -> str:
    _require_args("endsWith", args, 2)
    return f"({args[1]} = '' OR substr({args[0]}, -length({args[1]})) = {args[1]})"


def _format_date_time(args: list[str]) -> str:
    if len(args) == 2:
        return f"date_format({args[0]}, {args[1]})"
    if len(args) == 3:
        return f"date_format(at_timezone(with_timezone(CAST({args[0]} AS TIMESTAMP), 'UTC'), {args[2]}), {args[1]})"
    raise _invalid_arguments("formatDateTime", "formatDateTime expects a value, format, and optional timezone.")


def _from_unix_timestamp64_milli(args: list[str]) -> str:
    _require_args("fromUnixTimestamp64Milli", args, 1)
    return f"from_unixtime((CAST({args[0]} AS DOUBLE) / 1000e0))"


def _time_slot(args: list[str]) -> str:
    _require_args("timeSlot", args, 1)
    return f"date_add('minute', -mod(minute({args[0]}), 30), date_trunc('minute', {args[0]}))"


def _to_time(args: list[str]) -> str:
    _require_args("toTime", args, 1)
    seconds = f"hour({args[0]}) * 3600 + minute({args[0]}) * 60 + second({args[0]})"
    return f"date_add('second', {seconds}, TIMESTAMP '1970-01-02 00:00:00')"


def _time_slots(args: list[str]) -> str:
    if len(args) not in {2, 3}:
        raise _invalid_arguments("timeSlots", "timeSlots expects a start, duration, and optional slot size.")
    size = f"CAST({args[2]} AS BIGINT)" if len(args) == 3 else "BIGINT '1800'"
    start = f"CAST(floor(to_unixtime({args[0]})) AS BIGINT)"
    duration = f"CAST({args[1]} AS BIGINT)"
    first = f"{start} - mod({start}, {size})"
    last = f"{start} + {duration} - mod({start} + {duration}, {size})"
    values = f"transform(sequence({first}, {last}, {size}), __hogql_epoch -> CAST(from_unixtime(__hogql_epoch) AS TIMESTAMP))"
    return f"IF({size} > 0 AND {duration} >= 0, {values}, fail('timeSlots requires a positive size and non-negative duration'))"


def _right(args: list[str]) -> str:
    _require_args("right", args, 2)
    return (
        f"IF({args[1]} = 0, '', IF({args[1]} > 0, substr({args[0]}, -({args[1]})), "
        f"substr({args[0]}, greatest(1, -({args[1]}) + 1))))"
    )


def _left(args: list[str]) -> str:
    _require_args("left", args, 2)
    return (
        f"IF({args[1]} >= 0, substr({args[0]}, 1, {args[1]}), "
        f"substr({args[0]}, 1, greatest(length({args[0]}) + {args[1]}, 0)))"
    )


def _position(args: list[str]) -> str:
    _require_args("position", args, 2)
    return f"strpos({args[0]}, {args[1]})"


def _position_case_insensitive(args: list[str]) -> str:
    if len(args) == 2:
        return f"strpos(lower({args[0]}), lower({args[1]}))"
    if len(args) == 3:
        match = f"strpos(lower(substr({args[0]}, {args[2]})), lower({args[1]}))"
        return f"CASE WHEN {match} = 0 THEN 0 ELSE {match} + {args[2]} - 1 END"
    raise _invalid_arguments(
        "positionCaseInsensitive", "positionCaseInsensitive expects two or three arguments in Trino mode."
    )


def _replace_one(args: list[str]) -> str:
    _require_args("replaceOne", args, 3)
    source, pattern, replacement = args
    position = f"strpos({source}, {pattern})"
    return (
        f"CASE WHEN length({pattern}) = 0 OR {position} = 0 THEN {source} ELSE "
        f"concat(substr({source}, 1, {position} - 1), {replacement}, "
        f"substr({source}, {position} + length({pattern}))) END"
    )


def _float_or_null(args: list[str]) -> str:
    _require_args("toFloat64OrNull", args, 1)
    return f"TRY_CAST({args[0]} AS DOUBLE)"


def _array_slice(args: list[str]) -> str:
    if len(args) not in {2, 3}:
        raise _invalid_arguments("arraySlice", "arraySlice expects an array, offset, and optional length.")
    array, offset = args[:2]
    size = f"cardinality({array})"
    start = f"IF({offset} < 0, {size} + {offset} + 1, {offset})"
    end = size if len(args) == 2 else f"IF({args[2]} < 0, {size} + {args[2]}, {start} + {args[2]} - 1)"
    clipped_start = f"greatest(1, {start})"
    length = f"IF({offset} = 0, 0, greatest(0, {end} - {clipped_start} + 1))"
    return f"slice({array}, {clipped_start}, {length})"


def _array_intersect(args: list[str]) -> str:
    if not args:
        raise _invalid_arguments("arrayIntersect", "arrayIntersect expects at least one argument in Trino mode.")
    result = f"array_distinct({args[0]})"
    for arg in args[1:]:
        result = f"array_intersect({result}, {arg})"
    return result


def _cut_fragment(args: list[str]) -> str:
    _require_args("cutFragment", args, 1)
    return f"regexp_replace({args[0]}, '#.*$', '')"


def _cut_query_string(args: list[str]) -> str:
    _require_args("cutQueryString", args, 1)
    return f"regexp_replace({args[0]}, '\\?.*$', '')"


def _cut_query_string_and_fragment(args: list[str]) -> str:
    _require_args("cutQueryStringAndFragment", args, 1)
    return f"regexp_replace({args[0]}, '[?#].*$', '')"


def _map(args: list[str]) -> str:
    if not args or len(args) % 2 != 0:
        raise _invalid_arguments("map", "map expects one or more key/value pairs in Trino mode.")
    return f"map(ARRAY[{', '.join(args[::2])}], ARRAY[{', '.join(args[1::2])}])"


def _transform(args: list[str]) -> str:
    if len(args) not in {3, 4}:
        raise _invalid_arguments("transform", "transform expects three or four arguments in Trino mode.")
    value, source, target = args[:3]
    fallback = args[3] if len(args) == 4 else value
    return (
        f"CASE WHEN contains({source}, {value}) "
        f"THEN element_at({target}, array_position({source}, {value})) ELSE {fallback} END"
    )


def _to_monday(args: list[str]) -> str:
    _require_args("toMonday", args, 1)
    return f"CAST(date_trunc('week', {args[0]}) AS DATE)"


def _to_interval_month(args: list[str]) -> str:
    _require_args("toIntervalMonth", args, 1)
    return f"(CAST({args[0]} AS BIGINT) * INTERVAL '1' MONTH)"


def _scaled_month_interval(name: str, months: int) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"(CAST({args[0]} AS BIGINT) * INTERVAL '{months}' MONTH)"

    return handler


def _scaled_day_interval(name: str, days: int) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"(CAST({args[0]} AS BIGINT) * INTERVAL '{days}' DAY)"

    return handler


def _formatted_date_number(name: str, pattern: str, trino_type: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"CAST(date_format({args[0]}, '{pattern}') AS {trino_type})"

    return handler


def _e(args: list[str]) -> str:
    _require_args("e", args, 0)
    return "e()"


def _current_timestamp(args: list[str]) -> str:
    _require_args("current_timestamp", args, 0)
    return "CURRENT_TIMESTAMP"


def _unary_expression(name: str, template: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return template.format(value=args[0])

    return handler


def _binary_expression(name: str, template: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return template.format(left=args[0], right=args[1])

    return handler


def _array(args: list[str]) -> str:
    return f"ARRAY[{', '.join(args)}]"


def _array_pop_front(args: list[str]) -> str:
    _require_args("arrayPopFront", args, 1)
    return f"slice({args[0]}, 2, greatest(cardinality({args[0]}) - 1, 0))"


def _array_pop_back(args: list[str]) -> str:
    _require_args("arrayPopBack", args, 1)
    return f"slice({args[0]}, 1, greatest(cardinality({args[0]}) - 1, 0))"


def _array_push_front(args: list[str]) -> str:
    _require_args("arrayPushFront", args, 2)
    return f"concat(ARRAY[{args[1]}], {args[0]})"


def _array_push_back(args: list[str]) -> str:
    _require_args("arrayPushBack", args, 2)
    return f"concat({args[0]}, ARRAY[{args[1]}])"


def _array_resize(args: list[str]) -> str:
    if len(args) != 3:
        raise _invalid_arguments(
            "arrayResize",
            "The two-argument form needs a type-dependent default value. Trino mode requires an explicit value.",
        )
    array, size, value = args
    return (
        f"IF({size} >= 0, concat(slice({array}, 1, CAST({size} AS BIGINT)), "
        f"repeat({value}, greatest(CAST({size} AS BIGINT) - cardinality({array}), 0)), slice({array}, 1, 0)), "
        f"concat(repeat({value}, greatest(-(CAST({size} AS BIGINT)) - cardinality({array}), 0)), "
        f"slice({array}, greatest(cardinality({array}) + CAST({size} AS BIGINT) + 1, 1), "
        f"least(-(CAST({size} AS BIGINT)), cardinality({array}))), slice({array}, 1, 0)))"
    )


def _array_difference(args: list[str]) -> str:
    _require_args("arrayDifference", args, 1)
    value = args[0]
    return (
        f"IF(cardinality({value}) = 0, ARRAY[], "
        f"transform(sequence(1, cardinality({value})), __hogql_index -> "
        f"IF(__hogql_index = 1, 0, {value}[__hogql_index] - {value}[__hogql_index - 1])))"
    )


def _array_product(args: list[str]) -> str:
    _require_args("arrayProduct", args, 1)
    return (
        f"IF(cardinality({args[0]}) = 0, DOUBLE '0', "
        f"reduce({args[0]}, DOUBLE '1', (__hogql_total, __hogql_value) -> "
        f"__hogql_total * __hogql_value, __hogql_total -> __hogql_total))"
    )


def _array_uniq(args: list[str]) -> str:
    if not args:
        raise _invalid_arguments("arrayUniq", "arrayUniq expects at least one array.")
    value = args[0] if len(args) == 1 else f"zip({', '.join(args)})"
    return f"cardinality(array_distinct({value}))"


def _array_with_constant(args: list[str]) -> str:
    _require_args("arrayWithConstant", args, 2)
    return f"repeat({args[1]}, CAST({args[0]} AS BIGINT))"


def _base64_encode(args: list[str]) -> str:
    _require_args("base64Encode", args, 1)
    return f"to_base64(to_utf8({args[0]}))"


def _base58_encode(args: list[str]) -> str:
    _require_args("base58Encode", args, 1)
    value = "__hogql_base58_value"
    binary = f"to_utf8({value})"
    byte_count = f"length({binary})"
    positions = f"IF({byte_count} = 0, CAST(ARRAY[] AS ARRAY(BIGINT)), sequence(BIGINT '1', {byte_count}))"
    bytes_array = (
        f"transform({positions}, __hogql_base58_position -> "
        f"from_base(substr(to_hex({binary}), __hogql_base58_position * 2 - 1, 2), 16))"
    )
    state = "__hogql_base58_state"
    byte = "__hogql_base58_byte"
    carry_state = "__hogql_base58_carry_state"
    digit = "__hogql_base58_digit"
    converted = "__hogql_base58_converted"
    multiplied = (
        f"reduce({state}[1], ROW({byte}, CAST(ARRAY[] AS ARRAY(BIGINT))), "
        f"({carry_state}, {digit}) -> ROW(({carry_state}[1] + {digit} * 256) / 58, "
        f"concat({carry_state}[2], ARRAY[mod({carry_state}[1] + {digit} * 256, 58)])), "
        f"{carry_state} -> {carry_state})"
    )
    remaining_digits = (
        f"IF({converted}[1] = 0, CAST(ARRAY[] AS ARRAY(BIGINT)), "
        f"IF({converted}[1] < 58, ARRAY[{converted}[1]], "
        f"ARRAY[mod({converted}[1], 58), {converted}[1] / 58]))"
    )
    update = (
        f"IF(NOT {state}[3] AND {byte} = 0, ROW({state}[1], {state}[2] + 1, false), "
        f"element_at(transform(ARRAY[{multiplied}], {converted} -> "
        f"ROW(concat({converted}[2], {remaining_digits}), {state}[2], true)), 1))"
    )
    reduced = (
        f"reduce({bytes_array}, ROW(CAST(ARRAY[] AS ARRAY(BIGINT)), BIGINT '0', false), "
        f"({state}, {byte}) -> {update}, {state} -> {state})"
    )
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    encoded = (
        f"array_join(repeat('1', CAST({state}[2] AS INTEGER)), '') || "
        f"array_join(transform(reverse({state}[1]), {digit} -> substr('{alphabet}', {digit} + 1, 1)), '')"
    )
    result = f"element_at(transform(ARRAY[{reduced}], {state} -> {encoded}), 1)"
    return f"element_at(transform(ARRAY[{args[0]}], {value} -> IF({value} IS NULL, NULL, {result})), 1)"


def _base64_decode(args: list[str]) -> str:
    _require_args("base64Decode", args, 1)
    return f"from_utf8(from_base64({args[0]}))"


def _try_base64_decode(args: list[str]) -> str:
    _require_args("tryBase64Decode", args, 1)
    valid = (
        f"mod(length({args[0]}), 4) = 0 AND "
        f"regexp_like({args[0]}, '^(?:[A-Za-z0-9+/]{{4}})*(?:[A-Za-z0-9+/]{{2}}==|[A-Za-z0-9+/]{{3}}=)?$')"
    )
    return f"IF({valid}, coalesce(TRY(from_utf8(from_base64({args[0]}))), ''), '')"


def _ascii(args: list[str]) -> str:
    _require_args("ascii", args, 1)
    return f"IF({args[0]} = '', 0, from_base(to_hex(substr(to_utf8({args[0]}), 1, 1)), 16))"


def _concat_with_separator(args: list[str]) -> str:
    if len(args) < 2:
        raise _invalid_arguments("concatWithSeparator", "concatWithSeparator expects a separator and values.")
    null_check = " OR ".join(f"{arg} IS NULL" for arg in args)
    return f"IF({null_check}, NULL, array_join(ARRAY[{', '.join(args[1:])}], {args[0]}))"


def _split_by_whitespace(args: list[str]) -> str:
    _require_args("splitByWhitespace", args, 1)
    return f"IF(trim({args[0]}) = '', ARRAY[], regexp_split(trim({args[0]}), '\\s+'))"


def _map_contains(args: list[str]) -> str:
    _require_args("mapContains", args, 2)
    return f"contains(map_keys({args[0]}), {args[1]})"


def _map_lambda(name: str, target: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return f"{target}({args[1]}, {args[0]})"

    return handler


def _map_apply(args: list[str]) -> str:
    _require_args("mapApply", args, 2)
    transformed = f"transform_values({args[1]}, {args[0]})"
    return (
        f"map_from_entries(transform(map_entries({transformed}), "
        "__hogql_entry -> ROW(__hogql_entry[2][1], __hogql_entry[2][2])))"
    )


def _json_agg(args: list[str]) -> str:
    _require_args("json_agg", args, 1)
    return f"json_format(CAST(array_agg({args[0]}) AS JSON))"


def _string_agg(args: list[str]) -> str:
    _require_args("string_agg", args, 2)
    return f"array_join(array_agg({args[0]}), {args[1]})"


def _date_arithmetic(name: str, operator: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return f"({args[0]} {operator} {args[1]})"

    return handler


def _make_date(args: list[str]) -> str:
    _require_args("make_date", args, 3)
    value = f"TRY_CAST(format('%04d-%02d-%02d', {args[0]}, {args[1]}, {args[2]}) AS DATE)"
    return f"IF({value} BETWEEN DATE '1970-01-01' AND DATE '2149-06-06', {value}, DATE '1970-01-01')"


def _timezone(args: list[str]) -> str:
    _require_args("timezone", args, 2)
    return f"at_timezone(with_timezone(CAST({args[1]} AS TIMESTAMP), 'UTC'), {args[0]})"


def _timezone_offset(args: list[str]) -> str:
    _require_args("timeZoneOffset", args, 1)
    return f"(timezone_hour({args[0]}) * 3600 + timezone_minute({args[0]}) * 60)"


def _week_anchor(january_first: str, weekday: int, rule: str) -> str:
    if rule == "first":
        distance = f"mod({weekday} - day_of_week({january_first}) + 7, 7)"
        return f"date_add('day', {distance}, {january_first})"
    if rule == "four":
        january_fourth = f"date_add('day', 3, {january_first})"
        distance = f"mod(day_of_week({january_fourth}) - {weekday} + 7, 7)"
        return f"date_add('day', -{distance}, {january_fourth})"
    distance = f"mod(day_of_week({january_first}) - {weekday} + 7, 7)"
    return f"date_add('day', -{distance}, {january_first})"


def _week_value(date: str, january_first: str, weekday: int, rule: str, range_starts_at_one: bool) -> str:
    anchor = _week_anchor(january_first, weekday, rule)
    if not range_starts_at_one:
        return f"IF({date} < {anchor}, BIGINT '0', date_diff('day', {anchor}, {date}) / 7 + 1)"

    previous_january_first = f"date_add('year', -1, {january_first})"
    next_january_first = f"date_add('year', 1, {january_first})"
    previous_anchor = _week_anchor(previous_january_first, weekday, rule)
    next_anchor = _week_anchor(next_january_first, weekday, rule)
    return (
        f"CASE WHEN {date} < {anchor} THEN date_diff('day', {previous_anchor}, {date}) / 7 + 1 "
        f"WHEN {date} >= {next_anchor} THEN date_diff('day', {next_anchor}, {date}) / 7 + 1 "
        f"ELSE date_diff('day', {anchor}, {date}) / 7 + 1 END"
    )


def _year_week_value(date: str, january_first: str, weekday: int, rule: str) -> str:
    anchor = _week_anchor(january_first, weekday, rule)
    previous_january_first = f"date_add('year', -1, {january_first})"
    next_january_first = f"date_add('year', 1, {january_first})"
    previous_anchor = _week_anchor(previous_january_first, weekday, rule)
    next_anchor = _week_anchor(next_january_first, weekday, rule)
    year = f"year({date})"
    return (
        f"CASE WHEN {date} < {anchor} THEN ({year} - 1) * 100 + date_diff('day', {previous_anchor}, {date}) / 7 + 1 "
        f"WHEN {date} >= {next_anchor} THEN ({year} + 1) * 100 + date_diff('day', {next_anchor}, {date}) / 7 + 1 "
        f"ELSE {year} * 100 + date_diff('day', {anchor}, {date}) / 7 + 1 END"
    )


def _to_week(name: str, include_year: bool) -> Callable[[list[str]], str]:
    modes = {
        0: (7, "first", False),
        1: (1, "four", False),
        2: (7, "first", True),
        3: (1, "four", True),
        4: (7, "four", False),
        5: (1, "first", False),
        6: (7, "four", True),
        7: (1, "first", True),
        8: (7, "contains", True),
        9: (1, "contains", True),
    }

    def handler(args: list[str]) -> str:
        if len(args) not in {1, 2, 3}:
            raise _invalid_arguments(name, f"{name} expects a date, optional mode, and optional timezone.")
        date = f"CAST({args[0]} AS DATE)"
        if len(args) == 3:
            date = f"CAST(at_timezone(with_timezone(CAST({args[0]} AS TIMESTAMP), 'UTC'), {args[2]}) AS DATE)"
        mode = f"CAST({args[1]} AS INTEGER)" if len(args) >= 2 else "0"
        week = "__hogql_week[1]"
        january_first = f"date_trunc('year', {week})"
        branches = []
        for mode_number, (weekday, rule, range_starts_at_one) in modes.items():
            value = (
                _year_week_value(week, january_first, weekday, rule)
                if include_year
                else _week_value(week, january_first, weekday, rule, range_starts_at_one)
            )
            branches.append(f"WHEN {mode_number} THEN {value}")
        result = " ".join(branches)
        return (
            f"element_at(transform(ARRAY[ROW({date}, {mode})], __hogql_week -> "
            f"CASE __hogql_week[2] {result} ELSE fail('{name} mode must be between 0 and 9') END), 1)"
        )

    return handler


def _json_is_valid(args: list[str]) -> str:
    _require_args("isValidJSON", args, 1)
    return f"(TRY(json_parse(CAST({args[0]} AS VARCHAR))) IS NOT NULL)"


def _positive_modulo(args: list[str]) -> str:
    _require_args("positiveModulo", args, 2)
    return f"mod(mod({args[0]}, {args[1]}) + {args[1]}, {args[1]})"


def _or_zero(name: str, operator: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return f"IF({args[1]} = 0, 0, {operator.format(left=args[0], right=args[1])})"

    return handler


def _every(args: list[str]) -> str:
    _require_args("every", args, 1)
    return f"bool_and(CAST({args[0]} AS BOOLEAN))"


def _pad(name: str, target: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) not in {2, 3}:
            raise _invalid_arguments(name, f"{name} expects a string, length, and optional padding string.")
        padding = args[2] if len(args) == 3 else "' '"
        return f"{target}({args[0]}, {args[1]}, {padding})"

    return handler


def _array_avg(args: list[str]) -> str:
    if len(args) == 1:
        values = args[0]
    elif len(args) == 2:
        values = f"transform({args[1]}, {args[0]})"
    else:
        raise _invalid_arguments("arrayAvg", "arrayAvg expects an array or a lambda and an array.")
    return (
        f"IF(cardinality({values}) = 0, DOUBLE '0', "
        f"reduce({values}, DOUBLE '0', (__hogql_total, __hogql_value) -> "
        f"__hogql_total + __hogql_value, __hogql_total -> __hogql_total) / cardinality({values}))"
    )


def _array_compact(args: list[str]) -> str:
    _require_args("arrayCompact", args, 1)
    value = args[0]
    empty = f"slice({value}, 1, 0)"
    return (
        f"reduce({value}, {empty}, (__hogql_result, __hogql_value) -> "
        f"IF(cardinality(__hogql_result) = 0 OR element_at(__hogql_result, -1) IS DISTINCT FROM __hogql_value, "
        f"concat(__hogql_result, ARRAY[__hogql_value]), __hogql_result), __hogql_result -> __hogql_result)"
    )


def _array_enumerate_dense(args: list[str]) -> str:
    _require_args("arrayEnumerateDense", args, 1)
    value = args[0]
    return (
        f"IF(cardinality({value}) = 0, ARRAY[], "
        f"transform(sequence(1, cardinality({value})), __hogql_index -> "
        f"array_position(transform(array_distinct(slice({value}, 1, __hogql_index)), "
        f"__hogql_candidate -> __hogql_candidate IS NOT DISTINCT FROM {value}[__hogql_index]), TRUE)))"
    )


def _array_enumerate_uniq(args: list[str]) -> str:
    if not args:
        raise _invalid_arguments("arrayEnumerateUniq", "arrayEnumerateUniq expects at least one array.")
    value = args[0] if len(args) == 1 else f"zip({', '.join(args)})"
    return (
        f"IF(cardinality({value}) = 0, ARRAY[], "
        f"transform(sequence(1, cardinality({value})), __hogql_index -> "
        f"cardinality(filter(slice({value}, 1, __hogql_index), __hogql_value -> "
        f"__hogql_value IS NOT DISTINCT FROM {value}[__hogql_index]))))"
    )


def _array_index(name: str, target: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        matches = f"transform({args[1]}, {args[0]})"
        if target == "first":
            return f"coalesce(array_position({matches}, TRUE), 0)"
        position = f"array_position(reverse({matches}), TRUE)"
        return f"IF({position} = 0, 0, cardinality({args[1]}) - {position} + 1)"

    return handler


def _array_rotate(name: str, direction: int) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        value = args[0]
        amount = args[1] if direction > 0 else f"-({args[1]})"
        size = f"cardinality({value})"
        offset = f"mod(mod({amount}, {size}) + {size}, {size})"
        return (
            f"IF({size} = 0, {value}, concat(slice({value}, {offset} + 1, {size} - {offset}), "
            f"slice({value}, 1, {offset})))"
        )

    return handler


def _count_matches(name: str, case_insensitive: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        pattern = f"concat('(?i)', {args[1]})" if case_insensitive else args[1]
        return f"IF(length({args[1]}) = 0, 0, cardinality(regexp_extract_all({args[0]}, {pattern})))"

    return handler


def _count_substrings(name: str, case_insensitive: bool = False, utf8: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) not in {2, 3}:
            raise _invalid_arguments(name, f"{name} expects a string, substring, and optional start position.")
        value = "__hogql_substrings[1]"
        needle = "__hogql_substrings[2]"
        if case_insensitive:
            if utf8:
                value, needle = f"lower({value})", f"lower({needle})"
            else:
                alphabet = "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'"
                value, needle = f"translate({value}, {alphabet})", f"translate({needle}, {alphabet})"
        if len(args) == 3:
            value = f"substr({value}, greatest(CAST(__hogql_substrings[3] AS BIGINT), 1))"
        result = (
            f"IF(length({needle}) = 0, 0, "
            f"(length({value}) - length(replace({value}, {needle}, ''))) / length({needle}))"
        )
        if len(args) == 3 and not utf8:
            ascii_only = (
                "length(to_utf8(__hogql_substrings[1])) = length(__hogql_substrings[1]) AND "
                "length(to_utf8(__hogql_substrings[2])) = length(__hogql_substrings[2])"
            )
            result = f"IF({ascii_only}, {result}, fail('A byte start position requires ASCII strings'))"
        if case_insensitive and utf8:
            stable_case = (
                "all_match(regexp_extract_all(concat(__hogql_substrings[1], __hogql_substrings[2]), '(?s).'), "
                "__hogql_character -> length(to_utf8(__hogql_character)) = "
                "length(to_utf8(lower(__hogql_character))))"
            )
            result = (
                f"IF({stable_case}, {result}, "
                "fail('UTF-8 case conversion with a different byte length is not supported'))"
            )
        return f"element_at(transform(ARRAY[ROW({', '.join(args)})], __hogql_substrings -> {result}), 1)"

    return handler


def _locate(args: list[str]) -> str:
    if len(args) not in {2, 3}:
        raise _invalid_arguments("locate", "locate expects a substring, string, and optional start position.")
    needle = "to_hex(to_utf8(__hogql_locate[1]))"
    value = "to_hex(to_utf8(__hogql_locate[2]))"
    start = "greatest(CAST(__hogql_locate[3] AS BIGINT), 1)" if len(args) == 3 else "BIGINT '1'"
    offset_value = f"substr({value}, 2 * {start} - 1)"
    position = f"strpos({offset_value}, {needle})"
    result = (
        f"IF({start} > length({value}) / 2 + 1 OR {position} = 0, 0, {start} + CAST(({position} - 1) / 2 AS BIGINT))"
    )
    return f"element_at(transform(ARRAY[ROW({', '.join(args)})], __hogql_locate -> {result}), 1)"


def _has_subsequence(name: str, case_insensitive: bool, utf8: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        haystack = "__hogql_subsequence[1]"
        needle = "__hogql_subsequence[2]"
        if case_insensitive:
            if utf8:
                haystack, needle = f"lower({haystack})", f"lower({needle})"
            else:
                alphabet = "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'"
                haystack, needle = f"translate({haystack}, {alphabet})", f"translate({needle}, {alphabet})"

        def characters(value: str) -> str:
            if utf8:
                return f"regexp_extract_all({value}, '(?s).')"
            encoded = f"to_hex(to_utf8({value}))"
            count = f"length({encoded}) / 2"
            indexes = f"filter(sequence(1, greatest({count}, 1)), __hogql_index -> __hogql_index <= {count})"
            return f"transform({indexes}, __hogql_index -> substr({encoded}, 2 * __hogql_index - 1, 2))"

        haystack_characters = characters(haystack)
        needle_characters = characters(needle)
        relative_position = (
            "array_position(slice(__hogql_haystack, __hogql_position + 1, "
            "cardinality(__hogql_haystack)), __hogql_character)"
        )
        next_position = (
            f"element_at(transform(ARRAY[{relative_position}], __hogql_relative -> "
            "IF(__hogql_relative = 0, BIGINT '-1', __hogql_position + __hogql_relative)), 1)"
        )
        result = (
            f"reduce({needle_characters}, BIGINT '0', "
            "(__hogql_position, __hogql_character) -> "
            f"IF(__hogql_position < 0, BIGINT '-1', {next_position}), "
            "__hogql_position -> __hogql_position >= 0)"
        )
        result = f"element_at(transform(ARRAY[{haystack_characters}], __hogql_haystack -> {result}), 1)"
        if case_insensitive and utf8:
            stable_case = (
                "all_match(regexp_extract_all(concat(__hogql_subsequence[1], __hogql_subsequence[2]), '(?s).'), "
                "__hogql_character -> length(to_utf8(__hogql_character)) = "
                "length(to_utf8(lower(__hogql_character))))"
            )
            result = (
                f"IF({stable_case}, {result}, "
                "fail('UTF-8 case conversion with a different byte length is not supported'))"
            )
        return f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_subsequence -> {result}), 1)"

    return handler


def _extract_tokens(name: str, alpha_only: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) not in ({1, 2} if name != "tokens" else {1}):
            raise _invalid_arguments(name, f"{name} expects a string and optional maximum token count.")
        pattern = "'[A-Za-z]+'" if alpha_only else "'[\\p{L}\\p{N}]+'"
        tokens = f"regexp_extract_all({args[0]}, {pattern})"
        if len(args) == 2:
            tokens = f"IF({args[1]} = 0, {tokens}, slice({tokens}, 1, {args[1]}))"
        return tokens

    return handler


def _logical_xor(args: list[str]) -> str:
    if len(args) < 2:
        raise _invalid_arguments("xor", "xor expects at least two arguments.")
    values = ", ".join(f"CAST({arg} AS BOOLEAN)" for arg in args)
    return (
        f"reduce(ARRAY[{values}], false, (__hogql_xor, __hogql_value) -> "
        "IF(__hogql_value IS NULL, NULL, __hogql_xor <> __hogql_value), "
        "__hogql_xor -> __hogql_xor)"
    )


def _throw_if(args: list[str]) -> str:
    _require_args("throwIf", args, 2)
    return f"IF({args[0]} IS NULL, NULL, IF(CAST({args[0]} AS BOOLEAN), fail({args[1]}), 0))"


def _is_valid_utf8(args: list[str]) -> str:
    _require_args("isValidUTF8", args, 1)
    return f"IF({args[0]} IS NULL, NULL, true)"


def _regexp_quote_meta(args: list[str]) -> str:
    _require_args("regexpQuoteMeta", args, 1)
    return f"regexp_replace({args[0]}, '([\\\\|()^$.\\-\\[\\]?*+{{:\\x00])', '\\\\$1')"


def _initcap(args: list[str]) -> str:
    _require_args("initcap", args, 1)
    characters = f"regexp_extract_all({args[0]}, '(?s).')"
    state_type = "ROW(at_word_start BOOLEAN, value VARCHAR)"
    character = "__hogql_character"
    alphanumeric = f"regexp_like({character}, '[A-Za-z0-9]')"
    converted = f"IF(__hogql_state[1], upper({character}), lower({character}))"
    return (
        f"reduce({characters}, CAST(ROW(true, '') AS {state_type}), "
        f"(__hogql_state, {character}) -> IF({alphanumeric}, "
        f"CAST(ROW(false, concat(__hogql_state[2], {converted})) AS {state_type}), "
        f"CAST(ROW(true, concat(__hogql_state[2], {character})) AS {state_type})), "
        "__hogql_state -> __hogql_state[2])"
    )


def _ipv4_string_parts(value: str) -> tuple[str, str]:
    strict = r"'^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$'"
    octets = f"transform(split({value}, '.'), __hogql_octet -> TRY_CAST(__hogql_octet AS BIGINT))"
    valid = f"regexp_like({value}, {strict}) AND all_match({octets}, __hogql_octet -> __hogql_octet <= 255)"
    number = f"reduce({octets}, BIGINT '0', (__hogql_total, __hogql_octet) -> __hogql_total * 256 + __hogql_octet, __hogql_total -> __hogql_total)"
    return valid, number


def _is_ipv4_string(args: list[str]) -> str:
    _require_args("isIPv4String", args, 1)
    value = "__hogql_ip"
    valid, _ = _ipv4_string_parts(value)
    return f"element_at(transform(ARRAY[{args[0]}], {value} -> IF({value} IS NULL, NULL, {valid})), 1)"


def _is_ipv6_string(args: list[str]) -> str:
    _require_args("isIPv6String", args, 1)
    value = "__hogql_ip"
    valid = f"strpos({value}, ':') > 0 AND strpos({value}, '%') = 0 AND TRY_CAST({value} AS IPADDRESS) IS NOT NULL"
    return f"element_at(transform(ARRAY[{args[0]}], {value} -> IF({value} IS NULL, NULL, {valid})), 1)"


def _is_ip_address_in_range(args: list[str]) -> str:
    _require_args("isIPAddressInRange", args, 2)
    same_family = f"(strpos({args[0]}, ':') > 0) = (strpos({args[1]}, ':') > 0)"
    contains = f"contains({args[1]}, CAST({args[0]} AS IPADDRESS))"
    return f"IF({args[0]} IS NULL OR {args[1]} IS NULL, NULL, IF({contains}, {same_family}, false))"


def _ipv4_string_to_num(name: str, fallback: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        value = "__hogql_ip"
        valid, number = _ipv4_string_parts(value)
        result = number if not fallback else f"IF({valid}, {number}, {fallback})"
        if not fallback:
            result = f"IF({valid}, {number}, fail('Invalid IPv4 address'))"
        return f"element_at(transform(ARRAY[{args[0]}], {value} -> IF({value} IS NULL, NULL, {result})), 1)"

    return handler


def _ipv4_number_to_string(value: str) -> str:
    octets = (
        f"transform(ARRAY[24, 16, 8, 0], __hogql_shift -> "
        f"CAST(bitwise_and(bitwise_right_shift_arithmetic({value}, __hogql_shift), 255) AS VARCHAR))"
    )
    return f"array_join({octets}, '.')"


def _ipv4_num_to_string(args: list[str]) -> str:
    _require_args("IPv4NumToString", args, 1)
    value = "__hogql_ip"
    result = _ipv4_number_to_string(value)
    result = f"IF({value} BETWEEN 0 AND 4294967295, {result}, fail('IPv4 number is out of range'))"
    return f"element_at(transform(ARRAY[CAST({args[0]} AS BIGINT)], {value} -> IF({value} IS NULL, NULL, {result})), 1)"


def _to_ipv4(name: str, fallback: str | None) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) not in ({1, 2} if name == "toIPv4OrDefault" else {1}):
            raise _invalid_arguments(name, f"{name} received an invalid number of arguments.")
        value = "__hogql_ipv4"
        valid, number = _ipv4_string_parts(value)
        if name == "toIPv4OrDefault":
            default = f"CAST({args[1]} AS IPADDRESS)" if len(args) == 2 else "CAST('0.0.0.0' AS IPADDRESS)"
        elif fallback is None:
            default = "fail('Invalid IPv4 address')"
        elif fallback == "NULL":
            default = "CAST(NULL AS IPADDRESS)"
        else:
            default = "CAST('0.0.0.0' AS IPADDRESS)"
        result = f"IF({valid}, CAST({_ipv4_number_to_string(number)} AS IPADDRESS), {default})"
        return f"element_at(transform(ARRAY[CAST({args[0]} AS VARCHAR)], {value} -> IF({value} IS NULL, NULL, {result})), 1)"

    return handler


def _ipv4_cidr_to_range(args: list[str]) -> str:
    _require_args("IPv4CIDRToRange", args, 2)
    value = "__hogql_ipv4_cidr[1]"
    prefix = "__hogql_ipv4_cidr[2]"
    valid, number = _ipv4_string_parts(value)
    host_mask = f"bitwise_left_shift(BIGINT '1', CAST(32 - {prefix} AS INTEGER)) - 1"
    lower = f"({number} - bitwise_and({number}, {host_mask}))"
    upper = f"({lower} + {host_mask})"
    result = (
        f"ROW(CAST({_ipv4_number_to_string(lower)} AS IPADDRESS), CAST({_ipv4_number_to_string(upper)} AS IPADDRESS))"
    )
    checked = (
        f"IF(NOT ({valid}), fail('Invalid IPv4 address'), "
        f"IF({prefix} BETWEEN 0 AND 32, {result}, fail('IPv4 CIDR prefix must be between 0 and 32')))"
    )
    return (
        f"element_at(transform(ARRAY[ROW(CAST({args[0]} AS VARCHAR), CAST({args[1]} AS BIGINT))], "
        f"__hogql_ipv4_cidr -> IF({value} IS NULL OR {prefix} IS NULL, "
        f"CAST(NULL AS ROW(IPADDRESS, IPADDRESS)), {checked})), 1)"
    )


def _query_string_and_fragment(args: list[str]) -> str:
    _require_args("queryStringAndFragment", args, 1)
    query = _raw_url_query("__hogql_url")
    fragment = _raw_url_fragment("__hogql_url")
    result = f"IF({fragment} = '', {query}, concat({query}, '#', {fragment}))"
    return f"element_at(transform(ARRAY[{args[0]}], __hogql_url -> {result}), 1)"


def _netloc(args: list[str]) -> str:
    _require_args("netloc", args, 1)
    return f"regexp_extract({args[0]}, '^(?:(?:[A-Za-z][A-Za-z0-9+.-]*:)?//)?([^/?#]*)', 1)"


def _url_hierarchy(name: str, path_only: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        value = "__hogql_hierarchy_url"
        absolute = f"regexp_like({value}, '^[A-Za-z][A-Za-z0-9+.-]*://')"
        authority = f"regexp_extract({value}, '^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]*')"
        authority_length = "length(__hogql_authority)"
        question = f"strpos({value}, '?')"
        fragment = f"strpos({value}, '#')"
        path_end = (
            f"least(IF({question} = 0, length({value}) + 1, {question}), "
            f"IF({fragment} = 0, length({value}) + 1, {fragment}))"
        )
        after_authority = f"__hogql_position > {authority_length}"
        if path_only:
            after_authority = f"__hogql_position > {authority_length} + 1"
        slash_boundary = (
            f"({after_authority} AND substr({value}, __hogql_position, 1) = '/' AND __hogql_position < {path_end})"
        )
        marker_boundary = f"({after_authority} AND __hogql_position IN ({question}, {fragment}))"
        terminal_boundary = (
            f"({after_authority} AND __hogql_position = length({value}))"
            if path_only
            else f"__hogql_position = length({value})"
        )
        boundary = f"{slash_boundary} OR {marker_boundary} OR {terminal_boundary}"
        positions = (
            f"filter(sequence(1, greatest(length({value}), 1)), "
            f"__hogql_position -> __hogql_position <= length({value}) AND ({boundary}))"
        )
        prefix = (
            f"substr({value}, {authority_length} + 1, __hogql_position - {authority_length})"
            if path_only
            else f"substr({value}, 1, __hogql_position)"
        )
        hierarchy = f"transform({positions}, __hogql_position -> {prefix})"
        if path_only:
            hierarchy = f"IF({absolute}, {hierarchy}, ARRAY[])"
        else:
            hierarchy = f"IF({absolute}, {hierarchy}, IF({value} = '', ARRAY[], ARRAY[{value}]))"
        return (
            f"element_at(transform(ARRAY[{args[0]}], {value} -> IF({value} IS NULL, NULL, "
            f"element_at(transform(ARRAY[{authority}], __hogql_authority -> {hierarchy}), 1))), 1)"
        )

    return handler


def _cut_url_parameter(args: list[str]) -> str:
    _require_args("cutURLParameter", args, 2)
    url = "__hogql_cut_url_args[1]"
    name = "__hogql_cut_url_args[2]"
    hash_position = f"strpos({url}, '#')"
    before = f"IF({hash_position} = 0, {url}, substr({url}, 1, {hash_position} - 1))"
    fragment = f"IF({hash_position} = 0, '', substr({url}, {hash_position}))"
    query_position = "strpos(__hogql_cut_url[1], '?')"
    parameters = f"split(substr(__hogql_cut_url[1], {query_position} + 1), '&')"
    matches = (
        f"transform(__hogql_parameters, __hogql_parameter -> "
        f"strpos(__hogql_parameter, '=') > 0 AND split_part(__hogql_parameter, '=', 1) = {name})"
    )
    match_position = f"array_position({matches}, true)"
    remaining = (
        "transform(filter(sequence(1, cardinality(__hogql_parameters)), "
        "__hogql_position -> __hogql_position <> __hogql_match_position), "
        "__hogql_position -> element_at(__hogql_parameters, __hogql_position))"
    )
    result = (
        f"IF({query_position} = 0 OR __hogql_match_position = 0, {url}, "
        f"concat(substr(__hogql_cut_url[1], 1, {query_position}), array_join({remaining}, '&'), "
        "__hogql_cut_url[2]))"
    )
    return (
        f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_cut_url_args -> "
        f"IF({url} IS NULL OR {name} IS NULL, NULL, "
        f"element_at(transform(ARRAY[ROW({before}, {fragment})], __hogql_cut_url -> "
        f"element_at(transform(ARRAY[{parameters}], __hogql_parameters -> "
        f"element_at(transform(ARRAY[{match_position}], __hogql_match_position -> {result}), 1)), 1)), 1))), 1)"
    )


def _encode_xml_component(args: list[str]) -> str:
    _require_args("encodeXMLComponent", args, 1)
    result = args[0]
    for source, target in (
        ("'&'", "'&amp;'"),
        ("'<'", "'&lt;'"),
        ("'>'", "'&gt;'"),
        ("'\"'", "'&quot;'"),
        ("''''", "'&apos;'"),
    ):
        result = f"replace({result}, {source}, {target})"
    return result


def _decode_xml_component(args: list[str]) -> str:
    _require_args("decodeXMLComponent", args, 1)
    groups = "__hogql_xml_entity"
    codepoint = f"IF({groups}[1] IS NOT NULL, from_base({groups}[1], 16), CAST({groups}[2] AS BIGINT))"
    result = f"regexp_replace({args[0]}, '&#(?:[xX]([0-9A-Fa-f]+)|([0-9]+));', {groups} -> chr({codepoint}))"
    for source, target in (
        ("'&lt;'", "'<'"),
        ("'&gt;'", "'>'"),
        ("'&quot;'", "'\"'"),
        ("'&apos;'", "''''"),
        ("'&amp;'", "'&'"),
    ):
        result = f"replace({result}, {source}, {target})"
    return result


def _uuid_v7_to_datetime(args: list[str]) -> str:
    _require_args("UUIDv7ToDateTime", args, 1)
    milliseconds = f"from_base(substr(replace(CAST({args[0]} AS VARCHAR), '-', ''), 1, 12), 16)"
    return f"CAST(from_unixtime(({milliseconds}) / 1000e0) AS TIMESTAMP)"


def _make_timestamp(name: str, with_timezone_result: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        expected = 7 if with_timezone_result else 6
        _require_args(name, args, expected)
        parts = ", ".join(f"CAST({argument} AS BIGINT)" for argument in args[:5])
        seconds = f"CAST(truncate({args[5]}) AS BIGINT)"
        value = f"TRY_CAST(format('%04d-%02d-%02d %02d:%02d:%02d', {parts}, {seconds}) AS TIMESTAMP)"
        timestamp = (
            f"IF({value} BETWEEN TIMESTAMP '1970-01-01 00:00:00' AND TIMESTAMP '2106-02-07 06:28:15', "
            f"{value}, TIMESTAMP '1970-01-01 00:00:00')"
        )
        return f"with_timezone({timestamp}, {args[6]})" if with_timezone_result else timestamp

    return handler


def _sortable_semver(args: list[str]) -> str:
    _require_args("sortablesemver", args, 1)
    pattern = r"'^\s*v?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))(?:[-+][^\s]*)?\s*$'"
    matched = f"regexp_extract(coalesce({args[0]}, ''), {pattern}, 1)"
    return (
        f"element_at(transform(ARRAY[{matched}], __hogql_semver -> "
        "IF(__hogql_semver IS NULL, ARRAY[CAST(NULL AS BIGINT)], "
        "transform(split(__hogql_semver, '.'), __hogql_semver_part -> CAST(__hogql_semver_part AS BIGINT)))), 1)"
    )


def _point_in_ellipses(args: list[str]) -> str:
    if len(args) < 6 or (len(args) - 2) % 4 != 0:
        raise _invalid_arguments(
            "pointInEllipses", "pointInEllipses expects a point and one or more four-value ellipses."
        )
    tests = []
    for index in range(2, len(args), 4):
        center_x = index + 1
        center_y = index + 2
        radius_x = index + 3
        radius_y = index + 4
        tests.append(
            f"power((__hogql_ellipse[1] - __hogql_ellipse[{center_x}]) / __hogql_ellipse[{radius_x}], 2) + "
            f"power((__hogql_ellipse[2] - __hogql_ellipse[{center_y}]) / __hogql_ellipse[{radius_y}], 2) <= 1e0"
        )
    values = ", ".join(f"CAST({argument} AS DOUBLE)" for argument in args)
    nulls = " OR ".join(f"__hogql_ellipse[{index}] IS NULL" for index in range(1, len(args) + 1))
    return (
        f"element_at(transform(ARRAY[ROW({values})], __hogql_ellipse -> IF({nulls}, NULL, ({' OR '.join(tests)}))), 1)"
    )


def _if_not_finite(args: list[str]) -> str:
    _require_args("ifNotFinite", args, 2)
    return f"IF(is_finite(CAST({args[0]} AS DOUBLE)), {args[0]}, {args[1]})"


def _bar(args: list[str]) -> str:
    _require_args("bar", args, 4)
    value = "__hogql_bar[1]"
    minimum = "__hogql_bar[2]"
    maximum = "__hogql_bar[3]"
    width = "__hogql_bar[4]"
    ratio = f"greatest(0e0, least({width}, ({value} - {minimum}) / ({maximum} - {minimum}) * {width}))"
    eighths = f"CAST(floor({ratio} * 8) AS BIGINT)"
    full_blocks = f"{eighths} / 8"
    partial = f"CAST(mod({eighths}, 8) AS INTEGER)"
    result = (
        f"array_join(repeat('█', CAST({full_blocks} AS INTEGER)), '') || "
        f"IF({partial} = 0, '', substr('▏▎▍▌▋▊▉', {partial}, 1))"
    )
    return (
        f"element_at(transform(ARRAY[ROW(CAST({args[0]} AS DOUBLE), CAST({args[1]} AS DOUBLE), "
        f"CAST({args[2]} AS DOUBLE), CAST({args[3]} AS DOUBLE))], __hogql_bar -> "
        f"IF({value} IS NULL OR {minimum} IS NULL OR {maximum} IS NULL OR {width} IS NULL, NULL, {result})), 1)"
    )


def _ngrams(args: list[str]) -> str:
    _require_args("ngrams", args, 2)
    value = "__hogql_ngram_args[1]"
    size = "CAST(__hogql_ngram_args[2] AS BIGINT)"
    positions = (
        f"filter(sequence(1, greatest(length({value}) - {size} + 1, 1)), "
        f"__hogql_position -> __hogql_position <= length({value}) - {size} + 1)"
    )
    result = f"transform({positions}, __hogql_position -> substr({value}, __hogql_position, {size}))"
    return (
        f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_ngram_args -> "
        f"IF({value} IS NULL OR {size} IS NULL, NULL, IF({size} < 1, fail('ngrams requires a positive size'), "
        f"{result}))), 1)"
    )


def _has_tokens(name: str, require_all: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        haystack = "__hogql_token_array_args[1]"
        tokens = "__hogql_token_array_args[2]"
        token = "__hogql_token"
        escaped = f"regexp_replace({token}, '([\\\\|()^$.\\-\\[\\]?*+{{:\\x00])', '\\\\$1')"
        token_character = r"A-Za-z0-9\P{ASCII}"
        valid = f"{token} <> '' AND regexp_like({token}, '^[{token_character}]+$')"
        pattern = f"concat('(?:^|[^{token_character}])', {escaped}, '(?:$|[^{token_character}])')"
        match = f"{valid} AND regexp_like({haystack}, {pattern})"
        operation = "all_match" if require_all else "any_match"
        result = f"cardinality({tokens}) > 0 AND {operation}({tokens}, {token} -> {match})"
        return (
            f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_token_array_args -> "
            f"IF({haystack} IS NULL OR {tokens} IS NULL, NULL, {result})), 1)"
        )

    return handler


def _extract_ipv4_substrings(args: list[str]) -> str:
    _require_args("extractIPv4Substrings", args, 1)
    octet = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]?|0)"
    first_octet = rf"(?:(?<![0-9]){octet}|(?<=[0-9])[0-9])"
    return f"regexp_extract_all({args[0]}, '{first_octet}(?:\\.{octet}){{3}}')"


def _path_full(args: list[str]) -> str:
    _require_args("pathFull", args, 1)
    without_suffix = "regexp_replace(__hogql_url, '[?#].*$', '')"
    path = f"regexp_replace({without_suffix}, '^(?:[A-Za-z][A-Za-z0-9+.-]*:)?//[^/]*', '')"
    query = _raw_url_query("__hogql_url")
    fragment = _raw_url_fragment("__hogql_url")
    has_query = "strpos(split_part(__hogql_url, '#', 1), '?') > 0"
    result = (
        f"concat({path}, IF({has_query}, concat('?', {query}), ''), IF({fragment} = '', '', concat('#', {fragment})))"
    )
    return f"element_at(transform(ARRAY[{args[0]}], __hogql_url -> IF(strpos(__hogql_url, '/') = 0, '', {result})), 1)"


def _extract_url_parameters(name: str, names_only: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        query = _raw_url_query("__hogql_url")
        parameters = f"IF({query} = '', ARRAY[], split({query}, '&'))"
        if names_only:
            parameters = f"transform({parameters}, __hogql_parameter -> split_part(__hogql_parameter, '=', 1))"
        result = f"IF(__hogql_url IS NULL, NULL, {parameters})"
        return f"element_at(transform(ARRAY[{args[0]}], __hogql_url -> {result}), 1)"

    return handler


def _raw_url_query(value: str) -> str:
    return f"coalesce(regexp_extract(split_part({value}, '#', 1), '\\?(.*)$', 1), '')"


def _raw_url_fragment(value: str) -> str:
    return f"coalesce(regexp_extract({value}, '#(.*)$', 1), '')"


def _url_query_part(name: str, fragment: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        value = "__hogql_url"
        result = _raw_url_fragment(value) if fragment else _raw_url_query(value)
        return f"element_at(transform(ARRAY[{args[0]}], {value} -> IF({value} IS NULL, NULL, {result})), 1)"

    return handler


def _split_by_regexp(args: list[str]) -> str:
    if len(args) not in {2, 3}:
        raise _invalid_arguments("splitByRegexp", "splitByRegexp expects a pattern, string, and optional limit.")
    split = (
        f"IF({args[0]} = '', IF({args[1]} = '', ARRAY[], transform(sequence(1, length({args[1]})), "
        f"__hogql_index -> substr({args[1]}, __hogql_index, 1))), regexp_split({args[1]}, {args[0]}))"
    )
    return split if len(args) == 2 else f"slice({split}, 1, {args[2]})"


def _append_trailing_character(args: list[str]) -> str:
    _require_args("appendTrailingCharIfAbsent", args, 2)
    return (
        f"IF(length({args[1]}) <> 1, fail('appendTrailingCharIfAbsent expects one character'), "
        f"IF({args[0]} = '' OR {_ends_with(args)}, {args[0]}, concat({args[0]}, {args[1]})))"
    )


def _path(args: list[str]) -> str:
    _require_args("path", args, 1)
    return f"IF(strpos({args[0]}, '/') = 0, '', coalesce(url_extract_path({args[0]}), ''))"


def _map_key_like(name: str, extract: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        filtered = f"map_filter({args[0]}, (__hogql_key, __hogql_value) -> __hogql_key LIKE {args[1]})"
        return filtered if extract else f"cardinality({filtered}) > 0"

    return handler


def _bit_test(name: str, mode: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        if len(args) < 2:
            raise _invalid_arguments(name, f"{name} expects a value and bit positions.")
        tests = [f"bitwise_and({args[0]}, bitwise_left_shift(BIGINT '1', {position})) <> 0" for position in args[1:]]
        operator = " AND " if mode == "all" else " OR "
        return f"({operator.join(tests)})"

    return handler


def _bit_count(args: list[str]) -> str:
    _require_args("bitCount", args, 1)
    return f"bit_count({args[0]}, 64)"


def _bit_shift(name: str, target: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        return f"{target}({args[0]}, {args[1]})"

    return handler


def _domain_without_www(args: list[str]) -> str:
    _require_args("domainWithoutWWW", args, 1)
    return f"regexp_replace(coalesce(url_extract_host({args[0]}), ''), '^www\\.', '')"


def _url_string(name: str, target: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        return f"coalesce({target}({args[0]}), '')"

    return handler


def _port(args: list[str]) -> str:
    if len(args) not in {1, 2}:
        raise _invalid_arguments("port", "port expects a URL and an optional default port.")
    default = args[1] if len(args) == 2 else "0"
    return f"coalesce(url_extract_port({args[0]}), {default})"


def _bit_hamming_distance(args: list[str]) -> str:
    _require_args("bitHammingDistance", args, 2)
    return f"bit_count(bitwise_xor({args[0]}, {args[1]}), 64)"


def _cut_www(args: list[str]) -> str:
    _require_args("cutWWW", args, 1)
    return f"regexp_replace({args[0]}, '^(https?://)?www\\.', '$1')"


def _top_level_domain(args: list[str]) -> str:
    _require_args("topLevelDomain", args, 1)
    host = f"coalesce(url_extract_host({args[0]}), '')"
    return f"coalesce(element_at(split({host}, '.'), -1), '')"


def _l1_distance(args: list[str]) -> str:
    _require_args("L1Distance", args, 2)
    return f"reduce(zip_with({args[0]}, {args[1]}, (x, y) -> abs(x - y)), DOUBLE '0', (s, x) -> s + x, s -> s)"


def _linf_distance(args: list[str]) -> str:
    _require_args("LinfDistance", args, 2)
    return (
        f"IF(cardinality({args[0]}) = 0, DOUBLE '0', array_max(zip_with({args[0]}, {args[1]}, (x, y) -> abs(x - y))))"
    )


def _vector_norm(name: str, kind: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        if kind == "l1":
            return f"reduce(transform({args[0]}, x -> abs(x)), DOUBLE '0', (s, x) -> s + x, s -> s)"
        if kind == "l2":
            return f"sqrt(dot_product({args[0]}, {args[0]}))"
        return f"IF(cardinality({args[0]}) = 0, DOUBLE '0', array_max(transform({args[0]}, x -> abs(x))))"

    return handler


def _multi_search(name: str) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        haystack = "__hogql_search[1]"
        needle = "__hogql_needle"
        if "CaseInsensitive" in name:
            if "UTF8" in name:
                haystack, needle = f"lower({haystack})", f"lower({needle})"
            else:
                alphabet = "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'"
                haystack, needle = f"translate({haystack}, {alphabet})", f"translate({needle}, {alphabet})"
        position = f"strpos({haystack}, {needle})"
        if "UTF8" not in name:
            position = f"IF({position} = 0, 0, length(to_utf8(substr({haystack}, 1, {position} - 1))) + 1)"
        positions = f"transform(__hogql_search[2], __hogql_needle -> IF(__hogql_search[1] = '', 0, {position}))"
        if "AllPositions" in name:
            result = positions
        elif "FirstPosition" in name:
            result = f"coalesce(array_min(filter({positions}, __hogql_position -> __hogql_position > 0)), 0)"
        elif "FirstIndex" in name:
            result = f"array_position(transform({positions}, __hogql_position -> __hogql_position > 0), TRUE)"
        else:
            result = f"CAST(any_match({positions}, __hogql_position -> __hogql_position > 0) AS BIGINT)"
        if "CaseInsensitiveUTF8" in name:
            stable_case = (
                "all_match(regexp_extract_all(concat(__hogql_search[1], array_join(__hogql_search[2], '')), '(?s).'), "
                "__hogql_character -> length(to_utf8(__hogql_character)) = length(to_utf8(lower(__hogql_character))))"
            )
            result = f"IF({stable_case}, {result}, fail('UTF-8 case conversion with a different byte length is not supported'))"
        return f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_search -> {result}), 1)"

    return handler


def _round_down(args: list[str]) -> str:
    _require_args("roundDown", args, 2)
    return (
        f"element_at(transform(ARRAY[ROW({args[0]}, {args[1]})], __hogql_round -> "
        "IF(__hogql_round[1] IS NULL, NULL, IF(cardinality(__hogql_round[2]) = 0, fail('roundDown requires a non-empty boundary array'), "
        "IF(is_nan(CAST(__hogql_round[1] AS DOUBLE)), __hogql_round[1], "
        "coalesce(array_max(filter(__hogql_round[2], __hogql_boundary -> __hogql_boundary <= __hogql_round[1])), "
        "array_min(__hogql_round[2])))))), 1)"
    )


def _round_age(args: list[str]) -> str:
    _require_args("roundAge", args, 1)
    cases = " ".join(
        f"WHEN __hogql_age < {threshold} THEN {result}"
        for threshold, result in [(1, 0), (18, 17), (25, 18), (35, 25), (45, 35), (55, 45)]
    )
    return f"element_at(transform(ARRAY[{args[0]}], __hogql_age -> IF(__hogql_age IS NULL, NULL, CASE {cases} ELSE 55 END)), 1)"


def _round_duration(args: list[str]) -> str:
    _require_args("roundDuration", args, 1)
    buckets = [0, 1, 10, 30, 60, 120, 180, 240, 300, 600, 1200, 1800, 3600, 7200, 18000, 36000]
    cases = " ".join(
        f"WHEN __hogql_duration < {threshold} THEN {result}" for result, threshold in zip(buckets, buckets[1:])
    )
    return f"element_at(transform(ARRAY[{args[0]}], __hogql_duration -> IF(__hogql_duration IS NULL, NULL, CASE {cases} ELSE 36000 END)), 1)"


def _factorial(args: list[str]) -> str:
    _require_args("factorial", args, 1)
    values = ", ".join(str(factorial(value)) for value in range(21))
    return (
        f"element_at(transform(ARRAY[{args[0]}], __hogql_factorial -> "
        f"IF(__hogql_factorial > 20, fail('factorial requires an integer no greater than 20'), "
        f"element_at(ARRAY[{values}], CAST(greatest(__hogql_factorial, 0) + 1 AS BIGINT)))), 1)"
    )


def _modified_julian_day(name: str, reverse: bool) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 1)
        if reverse:
            return f"date_add('day', CAST({args[0]} AS BIGINT), DATE '1858-11-17')"
        return f"date_diff('day', DATE '1858-11-17', CAST({args[0]} AS DATE))"

    return handler


TRINO_FUNCTION_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "DATE": _cast("DATE", "DATE"),
    "toDate": _cast("toDate", "DATE"),
    "_toDate": _cast("_toDate", "DATE"),
    "toDateTime": _cast("toDateTime", "TIMESTAMP"),
    "toString": _cast("toString", "VARCHAR"),
    "toInt": _cast("toInt", "BIGINT"),
    "_toUInt64": _cast("_toUInt64", "BIGINT"),
    "toIntOrZero": _cast_or_default("toIntOrZero", "BIGINT", "0"),
    "toIntOrDefault": _cast_or_default("toIntOrDefault", "BIGINT", "0"),
    "toFloat": _cast("toFloat", "DOUBLE"),
    "toFloatOrZero": _cast_or_default("toFloatOrZero", "DOUBLE", "0e0"),
    "toFloatOrDefault": _cast_or_default("toFloatOrDefault", "DOUBLE", "0e0"),
    "toFloatOrNull": _float_or_null,
    "toFloat64OrNull": _float_or_null,
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
    "toISOWeek": _extract("toISOWeek", "WEEK"),
    "toISOYear": _extract("toISOYear", "YEAR_OF_WEEK"),
    "toYYYYMM": _formatted_date_number("toYYYYMM", "%Y%m", "INTEGER"),
    "toYYYYMMDD": _formatted_date_number("toYYYYMMDD", "%Y%m%d", "INTEGER"),
    "toYYYYMMDDhhmmss": _formatted_date_number("toYYYYMMDDhhmmss", "%Y%m%d%H%i%s", "BIGINT"),
    "toUnixTimestamp": _to_unix_timestamp,
    "fromUnixTimestamp64Milli": _from_unix_timestamp64_milli,
    "timeSlot": _time_slot,
    "timeSlots": _time_slots,
    "toTime": _to_time,
    "timeStampAdd": _date_arithmetic("timeStampAdd", "+"),
    "timeStampSub": _date_arithmetic("timeStampSub", "-"),
    "if": _if,
    "multiIf": _multi_if,
    "_caseWithExpression": _case_with_expression,
    "countIf": _count_if,
    "sumIf": _aggregate_if("sum"),
    "minIf": _aggregate_if("min"),
    "maxIf": _aggregate_if("max"),
    "avgIf": _aggregate_if("avg"),
    "anyIf": _aggregate_if("arbitrary"),
    "uniq": _uniq,
    "uniqExact": _uniq,
    "uniqIf": _uniq_if,
    "uniqExactIf": _uniq_if,
    "countDistinctIf": _uniq_if,
    "dateDiff": _date_diff,
    "date_diff": _date_diff,
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
    "toIntervalWeek": _scaled_day_interval("toIntervalWeek", 7),
    "toIntervalQuarter": _scaled_month_interval("toIntervalQuarter", 3),
    "toIntervalYear": _scaled_month_interval("toIntervalYear", 12),
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
    "divide": _divide,
    "divideDecimal": _divide_decimal,
    "modulo": _binary("modulo", "%"),
    "and": _logical("and", "AND"),
    "or": _logical("or", "OR"),
    "not": _not,
    "isNull": _null_check("isNull", False),
    "isNotNull": _null_check("isNotNull", True),
    "assumeNotNull": _identity("assumeNotNull"),
    "toNullable": _identity("toNullable"),
    "formatDateTime": _format_date_time,
    "to_char": _format_date_time,
    "position": _position,
    "positionCaseInsensitive": _position_case_insensitive,
    "right": _right,
    "replaceOne": _replace_one,
    "arraySlice": _array_slice,
    "arrayIntersect": _array_intersect,
    "cutFragment": _cut_fragment,
    "cutQueryString": _cut_query_string,
    "cutQueryStringAndFragment": _cut_query_string_and_fragment,
    "_toInt8": _cast("_toInt8", "TINYINT"),
    "_toInt16": _cast("_toInt16", "SMALLINT"),
    "_toInt32": _cast("_toInt32", "INTEGER"),
    "_toInt64": _cast("_toInt64", "BIGINT"),
    "to_date": _cast("to_date", "DATE"),
    "map": _map,
    "transform": _transform,
    "toMonday": _to_monday,
    "toIntervalMonth": _to_interval_month,
    "e": _e,
    "current_timestamp": _current_timestamp,
    "current_date": _today,
    "array": _array,
    "arrayPopFront": _array_pop_front,
    "arrayPopBack": _array_pop_back,
    "arrayPushFront": _array_push_front,
    "arrayPushBack": _array_push_back,
    "arrayResize": _array_resize,
    "arrayStringConcat": _array_string_concat,
    "arrayDifference": _array_difference,
    "arrayProduct": _array_product,
    "arrayUniq": _array_uniq,
    "arrayWithConstant": _array_with_constant,
    "base64Encode": _base64_encode,
    "base58Encode": _base58_encode,
    "base64Decode": _base64_decode,
    "tryBase64Decode": _try_base64_decode,
    "endsWith": _ends_with,
    "ascii": _ascii,
    "concatWithSeparator": _concat_with_separator,
    "left": _left,
    "leftPadUTF8": _pad("leftPadUTF8", "lpad"),
    "leftPad": _pad("leftPad", "lpad"),
    "rightPad": _pad("rightPad", "rpad"),
    "rightPadUTF8": _pad("rightPadUTF8", "rpad"),
    "positionUTF8": _position,
    "positionCaseInsensitiveUTF8": _position_case_insensitive,
    "splitByWhitespace": _split_by_whitespace,
    "splitByRegexp": _split_by_regexp,
    "appendTrailingCharIfAbsent": _append_trailing_character,
    "countMatches": _count_matches("countMatches"),
    "countMatchesCaseInsensitive": _count_matches("countMatchesCaseInsensitive", True),
    "countSubstrings": _count_substrings("countSubstrings"),
    "countSubstringsCaseInsensitive": _count_substrings("countSubstringsCaseInsensitive", True),
    "countSubstringsCaseInsensitiveUTF8": _count_substrings("countSubstringsCaseInsensitiveUTF8", True, True),
    "locate": _locate,
    "hasSubsequence": _has_subsequence("hasSubsequence", False, False),
    "hasSubsequenceCaseInsensitive": _has_subsequence("hasSubsequenceCaseInsensitive", True, False),
    "hasSubsequenceUTF8": _has_subsequence("hasSubsequenceUTF8", False, True),
    "hasSubsequenceCaseInsensitiveUTF8": _has_subsequence("hasSubsequenceCaseInsensitiveUTF8", True, True),
    "splitByNonAlpha": _extract_tokens("splitByNonAlpha", False),
    "alphaTokens": _extract_tokens("alphaTokens", True),
    "tokens": _extract_tokens("tokens", False),
    "xor": _logical_xor,
    "throwIf": _throw_if,
    "isValidUTF8": _is_valid_utf8,
    "regexpQuoteMeta": _regexp_quote_meta,
    "encodeXMLComponent": _encode_xml_component,
    "decodeXMLComponent": _decode_xml_component,
    "UUIDv7ToDateTime": _uuid_v7_to_datetime,
    "make_timestamp": _make_timestamp("make_timestamp", False),
    "make_timestamptz": _make_timestamp("make_timestamptz", True),
    "sortablesemver": _sortable_semver,
    "pointInEllipses": _point_in_ellipses,
    "ifNotFinite": _if_not_finite,
    "bar": _bar,
    "ngrams": _ngrams,
    "hasAllTokens": _has_tokens("hasAllTokens", True),
    "hasAnyTokens": _has_tokens("hasAnyTokens", False),
    "extractIPv4Substrings": _extract_ipv4_substrings,
    "hasToken": _has_token("hasToken", False, False),
    "hasTokenOrNull": _has_token("hasTokenOrNull", False, True),
    "hasTokenCaseInsensitive": _has_token("hasTokenCaseInsensitive", True, False),
    "hasTokenCaseInsensitiveOrNull": _has_token("hasTokenCaseInsensitiveOrNull", True, True),
    "initcap": _initcap,
    "isIPv4String": _is_ipv4_string,
    "isIPv6String": _is_ipv6_string,
    "isIPAddressInRange": _is_ip_address_in_range,
    "IPv4StringToNum": _ipv4_string_to_num("IPv4StringToNum", ""),
    "IPv4StringToNumOrDefault": _ipv4_string_to_num("IPv4StringToNumOrDefault", "0"),
    "IPv4StringToNumOrNull": _ipv4_string_to_num("IPv4StringToNumOrNull", "NULL"),
    "IPv4NumToString": _ipv4_num_to_string,
    "toIPv4": _to_ipv4("toIPv4", None),
    "toIPv4OrDefault": _to_ipv4("toIPv4OrDefault", "default"),
    "toIPv4OrNull": _to_ipv4("toIPv4OrNull", "NULL"),
    "toIPv4OrZero": _to_ipv4("toIPv4OrZero", "zero"),
    "IPv4CIDRToRange": _ipv4_cidr_to_range,
    "toValidUTF8": _identity("toValidUTF8"),
    "mapContains": _map_contains,
    "mapApply": _map_apply,
    "mapFilter": _map_lambda("mapFilter", "map_filter"),
    "mapContainsKeyLike": _map_key_like("mapContainsKeyLike", False),
    "mapExtractKeyLike": _map_key_like("mapExtractKeyLike", True),
    "json_agg": _json_agg,
    "string_agg": _string_agg,
    "every": _every,
    "stddevPopIf": _aggregate_if("stddev_pop"),
    "stddevSampIf": _aggregate_if("stddev_samp"),
    "varPopIf": _aggregate_if("var_pop"),
    "varSampIf": _aggregate_if("var_samp"),
    "covarPopIf": _aggregate_if("covar_pop"),
    "covarSampIf": _aggregate_if("covar_samp"),
    "groupBitAndIf": _aggregate_if("bitwise_and_agg"),
    "groupBitOrIf": _aggregate_if("bitwise_or_agg"),
    "groupBitXorIf": _aggregate_if("bitwise_xor_agg"),
    "date_add": _date_arithmetic("date_add", "+"),
    "date_subtract": _date_arithmetic("date_subtract", "-"),
    "make_date": _make_date,
    "monthName": _unary_expression("monthName", "date_format({value}, '%M')"),
    "timeZoneOf": _unary_expression("timeZoneOf", "timezone({value})"),
    "toUnixTimestamp64Milli": _unary_expression(
        "toUnixTimestamp64Milli", "CAST(to_unixtime({value}) * 1000 AS BIGINT)"
    ),
    "timezone": _timezone,
    "timeZoneOffset": _timezone_offset,
    "toWeek": _to_week("toWeek", False),
    "toYearWeek": _to_week("toYearWeek", True),
    "isValidJSON": _json_is_valid,
    "max2": _binary_expression("max2", "greatest({left}, {right})"),
    "min2": _binary_expression("min2", "least({left}, {right})"),
    "negate": _unary_expression("negate", "-({value})"),
    "positiveModulo": _positive_modulo,
    "intDivOrZero": _or_zero("intDivOrZero", "CAST({left} AS BIGINT) / CAST({right} AS BIGINT)"),
    "moduloOrZero": _or_zero("moduloOrZero", "mod({left}, {right})"),
    "acosh": _unary_expression("acosh", "ln({value} + sqrt({value} * {value} - 1))"),
    "asinh": _unary_expression("asinh", "ln({value} + sqrt({value} * {value} + 1))"),
    "atanh": _unary_expression("atanh", "0.5 * ln((1 + {value}) / (1 - {value}))"),
    "cosh": _unary_expression("cosh", "(exp({value}) + exp(-({value}))) / 2"),
    "exp10": _unary_expression("exp10", "power(10, {value})"),
    "exp2": _unary_expression("exp2", "power(2, {value})"),
    "hypot": _binary_expression("hypot", "sqrt({left} * {left} + {right} * {right})"),
    "intExp10": _unary_expression("intExp10", "CAST(power(10, {value}) AS BIGINT)"),
    "intExp2": _unary_expression("intExp2", "CAST(power(2, {value}) AS BIGINT)"),
    "log1p": _unary_expression("log1p", "ln(1 + {value})"),
    "sinh": _unary_expression("sinh", "(exp({value}) - exp(-({value}))) / 2"),
    "tanh": _unary_expression("tanh", "(exp({value}) - exp(-({value}))) / (exp({value}) + exp(-({value})))"),
    "_toUInt8": _cast("_toUInt8", "SMALLINT"),
    "arrayAvg": _array_avg,
    "arrayCompact": _array_compact,
    "arrayEnumerateDense": _array_enumerate_dense,
    "arrayEnumerateUniq": _array_enumerate_uniq,
    "arrayFirstIndex": _array_index("arrayFirstIndex", "first"),
    "arrayLastIndex": _array_index("arrayLastIndex", "last"),
    "arrayRotateLeft": _array_rotate("arrayRotateLeft", 1),
    "arrayRotateRight": _array_rotate("arrayRotateRight", -1),
    "bitTest": _bit_test("bitTest", "any"),
    "bitTestAll": _bit_test("bitTestAll", "all"),
    "bitTestAny": _bit_test("bitTestAny", "any"),
    "bitCount": _bit_count,
    "bitHammingDistance": _bit_hamming_distance,
    "bitShiftLeft": _bit_shift("bitShiftLeft", "bitwise_left_shift"),
    "bitShiftRight": _bit_shift("bitShiftRight", "bitwise_right_shift_arithmetic"),
    "domain": _url_string("domain", "url_extract_host"),
    "domainWithoutWWW": _domain_without_www,
    "protocol": _url_string("protocol", "url_extract_protocol"),
    "queryString": _url_query_part("queryString", False),
    "fragment": _url_query_part("fragment", True),
    "queryStringAndFragment": _query_string_and_fragment,
    "URLHierarchy": _url_hierarchy("URLHierarchy", False),
    "URLPathHierarchy": _url_hierarchy("URLPathHierarchy", True),
    "netloc": _netloc,
    "cutURLParameter": _cut_url_parameter,
    "pathFull": _path_full,
    "path": _path,
    "extractURLParameters": _extract_url_parameters("extractURLParameters", False),
    "extractURLParameterNames": _extract_url_parameters("extractURLParameterNames", True),
    "port": _port,
    "cutWWW": _cut_www,
    "topLevelDomain": _top_level_domain,
    "L1Distance": _l1_distance,
    "LinfDistance": _linf_distance,
    "L1Norm": _vector_norm("L1Norm", "l1"),
    "L2Norm": _vector_norm("L2Norm", "l2"),
    "LinfNorm": _vector_norm("LinfNorm", "linf"),
    "toModifiedJulianDay": _modified_julian_day("toModifiedJulianDay", False),
    "fromModifiedJulianDay": _modified_julian_day("fromModifiedJulianDay", True),
}

TRINO_FUNCTION_RENAMES_LOWER = {name.lower(): target for name, target in TRINO_FUNCTION_RENAMES.items()}
TRINO_FUNCTION_HANDLERS.update(
    {
        name: _multi_search(name)
        for operation in ("AllPositions", "FirstPosition", "FirstIndex", "Any")
        for suffix in ("", "UTF8", "CaseInsensitive", "CaseInsensitiveUTF8")
        if (name := f"multiSearch{operation}{suffix}") != "multiSearchAnyCaseInsensitive"
    }
)
TRINO_FUNCTION_HANDLERS.update(
    {
        "roundDown": _round_down,
        "roundAge": _round_age,
        "roundDuration": _round_duration,
        "roundToExp2": _identity("roundToExp2"),
        "gcd": _identity("gcd"),
        "lcm": _identity("lcm"),
        "JSONType": _identity("JSONType"),
        "date_bin": _identity("date_bin"),
        "arrayAUC": _identity("arrayAUC"),
        "tupleToNameValuePairs": _identity("tupleToNameValuePairs"),
        "mapPopulateSeries": _identity("mapPopulateSeries"),
        "toTypeName": _identity("toTypeName"),
        "bitNot": _identity("bitNot"),
        "indexHint": _constant("indexHint", "1"),
        "factorial": _factorial,
        "formatReadableSize": _format_readable(
            "formatReadableSize", 1024, ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
        ),
        "formatReadableDecimalSize": _format_readable(
            "formatReadableDecimalSize", 1000, ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        ),
        "formatReadableQuantity": _format_readable(
            "formatReadableQuantity",
            1000,
            (
                "",
                "thousand",
                "million",
                "billion",
                "trillion",
                "quadrillion",
                "quintillion",
                "sextillion",
                "septillion",
                "octillion",
                "nonillion",
                "decillion",
                "undecillion",
                "duodecillion",
                "tredecillion",
                "quattuordecillion",
                "quindecillion",
                "sexdecillion",
                "septendecillion",
                "octodecillion",
                "novemdecillion",
                "vigintillion",
            ),
        ),
    }
)
TRINO_FUNCTION_HANDLERS_LOWER = {name.lower(): handler for name, handler in TRINO_FUNCTION_HANDLERS.items()}

TRINO_PASSTHROUGH_FUNCTIONS = frozenset(
    {
        "abs",
        "acos",
        "array_agg",
        "asin",
        "atan",
        "atan2",
        "avg",
        "cardinality",
        "cbrt",
        "ceil",
        "coalesce",
        "concat",
        "cos",
        "count",
        "date_trunc",
        "degrees",
        "dense_rank",
        "exp",
        "floor",
        "greatest",
        "json_value",
        "lag",
        "lead",
        "last_value",
        "least",
        "length",
        "ln",
        "log10",
        "log2",
        "lower",
        "lpad",
        "ltrim",
        "max",
        "min",
        "nullif",
        "nth_value",
        "pow",
        "power",
        "pi",
        "radians",
        "rank",
        "replace",
        "reverse",
        "round",
        "row_number",
        "rpad",
        "rtrim",
        "sign",
        "sin",
        "sqrt",
        "sum",
        "substring",
        "tan",
        "trim",
        "upper",
    }
)
