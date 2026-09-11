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
    "endsWith": "ends_with",
    "rand": "random",
    "dateTrunc": "date_trunc",
    "substringUTF8": "substring",
    "lowerUTF8": "lower",
    "upperUTF8": "upper",
    "encodeURLComponent": "url_encode",
    "lengthUTF8": "length",
    "toLastDayOfMonth": "last_day_of_month",
    "mapFromArrays": "map",
    "mapUpdate": "map_concat",
    "log": "ln",
    "path": "url_extract_path",
    "decodeURLComponent": "url_decode",
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
    "bitNot": "bitwise_not",
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


def _format_date_time(args: list[str]) -> str:
    if len(args) == 2:
        return f"date_format({args[0]}, {args[1]})"
    if len(args) == 3:
        return f"date_format(at_timezone(with_timezone(CAST({args[0]} AS TIMESTAMP), 'UTC'), {args[2]}), {args[1]})"
    raise _invalid_arguments("formatDateTime", "formatDateTime expects a value, format, and optional timezone.")


def _from_unix_timestamp64_milli(args: list[str]) -> str:
    _require_args("fromUnixTimestamp64Milli", args, 1)
    return f"from_unixtime((CAST({args[0]} AS DOUBLE) / 1000e0))"


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
        f"repeat({value}, greatest(CAST({size} AS BIGINT) - cardinality({array}), 0))), "
        f"concat(repeat({value}, greatest(-(CAST({size} AS BIGINT)) - cardinality({array}), 0)), "
        f"slice({array}, greatest(cardinality({array}) + CAST({size} AS BIGINT) + 1, 1), "
        f"least(-(CAST({size} AS BIGINT)), cardinality({array})))))"
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


def _base64_decode(args: list[str]) -> str:
    _require_args("base64Decode", args, 1)
    return f"from_utf8(from_base64({args[0]}))"


def _try_base64_decode(args: list[str]) -> str:
    _require_args("tryBase64Decode", args, 1)
    return f"coalesce(TRY(from_utf8(from_base64({args[0]}))), '')"


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
    return f"CAST(format('%04d-%02d-%02d', {args[0]}, {args[1]}, {args[2]}) AS DATE)"


def _timezone(args: list[str]) -> str:
    _require_args("timezone", args, 2)
    return f"at_timezone(with_timezone(CAST({args[1]} AS TIMESTAMP), 'UTC'), {args[0]})"


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


def _count_substrings(name: str, case_insensitive: bool = False) -> Callable[[list[str]], str]:
    def handler(args: list[str]) -> str:
        _require_args(name, args, 2)
        value = f"lower({args[0]})" if case_insensitive else args[0]
        needle = f"lower({args[1]})" if case_insensitive else args[1]
        return (
            f"IF(length({needle}) = 0, 0, "
            f"(length({value}) - length(replace({value}, {needle}, ''))) / length({needle}))"
        )

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
        f"IF({args[0]} = '' OR ends_with({args[0]}, {args[1]}), {args[0]}, concat({args[0]}, {args[1]})))"
    )


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
        tests = [
            f"bitwise_and({args[0]}, bitwise_left_shift(BIGINT '1', {position})) <> 0" for position in args[1:]
        ]
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
        f"IF(cardinality({args[0]}) = 0, DOUBLE '0', "
        f"array_max(zip_with({args[0]}, {args[1]}, (x, y) -> abs(x - y))))"
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
    "arrayDifference": _array_difference,
    "arrayProduct": _array_product,
    "arrayUniq": _array_uniq,
    "arrayWithConstant": _array_with_constant,
    "base64Encode": _base64_encode,
    "base64Decode": _base64_decode,
    "tryBase64Decode": _try_base64_decode,
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
    "toValidUTF8": _identity("toValidUTF8"),
    "mapContains": _map_contains,
    "mapApply": _map_lambda("mapApply", "transform_entries"),
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
    "queryString": _url_string("queryString", "url_extract_query"),
    "fragment": _url_string("fragment", "url_extract_fragment"),
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
