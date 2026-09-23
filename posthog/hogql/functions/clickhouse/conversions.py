from posthog.hogql import ast
from posthog.hogql.ast import (
    ArrayType,
    BooleanType,
    DateTimeType,
    DateType,
    DecimalType,
    FloatType,
    IntegerType,
    IntervalType,
    StringType,
    UUIDType,
)
from posthog.hogql.base import UnknownType

from ..core import HogQLFunctionMeta


def _nullable_cast(clickhouse_type: str) -> HogQLFunctionMeta:
    """A cast that yields NULL on unparseable input, which is how HogQL spells every numeric cast."""
    return HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value=clickhouse_type)])


# ClickHouse writes the target width into the name, HogQL leaves it out. Callers reach for the
# ClickHouse spelling first, so accept the 64-bit ones as aliases: Int64 and Float64 are the widths
# `toInt` and `toFloat` already cast to. The narrower widths stay unmapped on purpose, because an
# alias there would silently widen the range a cast accepts instead of overflowing as ClickHouse
# does. Bare `toInt64`/`toFloat64` throw in ClickHouse where these return NULL, which is the same
# trade `toInt` and `toFloat` already make.
_TO_INT = _nullable_cast("Int64")
_TO_FLOAT = _nullable_cast("Float64")
_TO_INT_OR_ZERO = HogQLFunctionMeta("toInt64OrZero", 1, 1, signatures=[((StringType(),), IntegerType())])
_TO_FLOAT_OR_ZERO = HogQLFunctionMeta("toFloat64OrZero", 1, 1, signatures=[((StringType(),), FloatType())])
_TO_INT_OR_DEFAULT = HogQLFunctionMeta(
    # Mirror of toFloatOrDefault: ClickHouse's toInt64OrDefault requires the default value to
    # already be Int64, so cast it (any numeric/string literal then works). The 1-arg form is
    # degenerate (equivalent to toIntOrZero) and is rewritten in the printer before the
    # placeholder template renders.
    # Defaults are Integer only: accurateCast of a fractional float (e.g. 0.5) to Int64 throws
    # at runtime, so unlike toFloatOrDefault we don't accept Float-typed defaults.
    "toInt64OrDefault({0}, accurateCast({1}, 'Int64'))",
    1,
    2,
    using_placeholder_arguments=True,
    using_positional_arguments=True,
    signatures=[
        ((DecimalType(),), IntegerType()),
        ((IntegerType(),), IntegerType()),
        ((FloatType(),), IntegerType()),
        ((StringType(),), IntegerType()),
        ((DecimalType(), IntegerType()), IntegerType()),
        ((IntegerType(), IntegerType()), IntegerType()),
        ((FloatType(), IntegerType()), IntegerType()),
        ((StringType(), IntegerType()), IntegerType()),
    ],
)
_TO_FLOAT_OR_DEFAULT = HogQLFunctionMeta(
    # ClickHouse's toFloat64OrDefault requires the default value to already be
    # Float64 — passing e.g. an integer 0 raises "Default value type should be
    # same as cast type". Cast the default so any numeric/string literal works.
    # The 1-arg form is degenerate (equivalent to toFloatOrZero) and is
    # rewritten in the printer before the placeholder template renders.
    "toFloat64OrDefault({0}, accurateCast({1}, 'Float64'))",
    1,
    2,
    using_placeholder_arguments=True,
    using_positional_arguments=True,
    # The default arg (second) may be an integer or float literal — the
    # template casts it to Float64 either way, so both must resolve.
    signatures=[
        ((DecimalType(),), FloatType()),
        ((IntegerType(),), FloatType()),
        ((FloatType(),), FloatType()),
        ((StringType(),), FloatType()),
        ((DecimalType(), FloatType()), FloatType()),
        ((DecimalType(), IntegerType()), FloatType()),
        ((IntegerType(), FloatType()), FloatType()),
        ((IntegerType(), IntegerType()), FloatType()),
        ((FloatType(), FloatType()), FloatType()),
        ((FloatType(), IntegerType()), FloatType()),
        ((StringType(), FloatType()), FloatType()),
        ((StringType(), IntegerType()), FloatType()),
    ],
)
# type conversions
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
TYPE_CONVERSION_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "hex": HogQLFunctionMeta("hex", 1, 1),
    "unhex": HogQLFunctionMeta("unhex", 1, 1),
    # instead of just "reinterpret" we use specific list of "reinterpretAs*"" functions
    # that we know are safe to use to minimize the security risk
    "reinterpretAsUInt8": HogQLFunctionMeta("reinterpretAsUInt8", 1, 1),
    "reinterpretAsUInt16": HogQLFunctionMeta("reinterpretAsUInt16", 1, 1),
    "reinterpretAsUInt32": HogQLFunctionMeta("reinterpretAsUInt32", 1, 1),
    "reinterpretAsUInt64": HogQLFunctionMeta("reinterpretAsUInt64", 1, 1),
    "reinterpretAsUInt128": HogQLFunctionMeta("reinterpretAsUInt128", 1, 1),
    "reinterpretAsUInt256": HogQLFunctionMeta("reinterpretAsUInt256", 1, 1),
    "reinterpretAsInt8": HogQLFunctionMeta("reinterpretAsInt8", 1, 1),
    "reinterpretAsInt16": HogQLFunctionMeta("reinterpretAsInt16", 1, 1),
    "reinterpretAsInt32": HogQLFunctionMeta("reinterpretAsInt32", 1, 1),
    "reinterpretAsInt64": HogQLFunctionMeta("reinterpretAsInt64", 1, 1),
    "reinterpretAsInt128": HogQLFunctionMeta("reinterpretAsInt128", 1, 1),
    "reinterpretAsInt256": HogQLFunctionMeta("reinterpretAsInt256", 1, 1),
    "reinterpretAsFloat32": HogQLFunctionMeta("reinterpretAsFloat32", 1, 1),
    "reinterpretAsFloat64": HogQLFunctionMeta("reinterpretAsFloat64", 1, 1),
    "reinterpretAsUUID": HogQLFunctionMeta("reinterpretAsUUID", 1, 1),
    "accurateCast": HogQLFunctionMeta("accurateCast", 2, 2),
    "accurateCastOrNull": HogQLFunctionMeta("accurateCastOrNull", 2, 2),
    "toInt": _TO_INT,
    "toIntOrNull": _TO_INT,
    "toInt64": _TO_INT,
    "toInt64OrNull": _TO_INT,
    "toIntOrZero": _TO_INT_OR_ZERO,
    "toInt64OrZero": _TO_INT_OR_ZERO,
    "toIntOrDefault": _TO_INT_OR_DEFAULT,
    "toInt64OrDefault": _TO_INT_OR_DEFAULT,
    "_toInt8": HogQLFunctionMeta("toInt8", 1, 1),
    "_toInt16": HogQLFunctionMeta("toInt16", 1, 1),
    "_toInt32": HogQLFunctionMeta("toInt32", 1, 1),
    "_toInt64": HogQLFunctionMeta("toInt64", 1, 1),
    "_toUInt8": HogQLFunctionMeta("toUInt8", 1, 1, signatures=[((UnknownType(),), IntegerType())]),
    "_toUInt64": HogQLFunctionMeta("toUInt64", 1, 1, signatures=[((UnknownType(),), IntegerType())]),
    "_toUInt128": HogQLFunctionMeta("toUInt128", 1, 1),
    "toFloat": _TO_FLOAT,
    "toFloatOrNull": _TO_FLOAT,
    "toFloat64": _TO_FLOAT,
    "toFloat64OrNull": _TO_FLOAT,
    "toFloatOrZero": _TO_FLOAT_OR_ZERO,
    "toFloat64OrZero": _TO_FLOAT_OR_ZERO,
    "toFloatOrDefault": _TO_FLOAT_OR_DEFAULT,
    "toFloat64OrDefault": _TO_FLOAT_OR_DEFAULT,
    "toDecimal": HogQLFunctionMeta(
        "accurateCastOrNull",
        2,
        2,
        passthrough_suffix_args_count=1,
        suffix_args=[ast.Constant(value="Decimal64({0})")],  # Scale for Decimal64 is customizable
    ),
    "_toDate": HogQLFunctionMeta("toDate", 1, 1),
    "toUUID": HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="UUID")]),
    "toUUIDOrDefault": HogQLFunctionMeta("toUUIDOrDefault", 2, 2),
    "toString": HogQLFunctionMeta(
        "toString",
        1,
        2,
        signatures=[
            ((IntegerType(),), StringType()),
            ((StringType(),), StringType()),
            ((FloatType(),), StringType()),
            ((DateType(),), StringType()),
            ((DateType(), StringType()), StringType()),
            ((DateTimeType(),), StringType()),
            ((DateTimeType(), StringType()), StringType()),
        ],
    ),
    "toNullableString": HogQLFunctionMeta(
        "accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="Nullable(String)")]
    ),
    "toBool": HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="Bool")]),
    "toJSONString": HogQLFunctionMeta("toJSONString", 1, 1),
    "parseDateTime": HogQLFunctionMeta("parseDateTimeOrNull", 2, 3, tz_aware=True),
    "parseDateTimeBestEffort": HogQLFunctionMeta("parseDateTime64BestEffortOrNull", 1, 2, tz_aware=True),
    "dynamicType": HogQLFunctionMeta("dynamicType", 1, 1),
    "toTypeName": HogQLFunctionMeta("toTypeName", 1, 1),
    "defaultValueOfTypeName": HogQLFunctionMeta("defaultValueOfTypeName", 1, 1),
    "cityHash64": HogQLFunctionMeta("cityHash64", 1, 1),
    "MD5": HogQLFunctionMeta("MD5", 1, 1),
    "UUIDv7ToDateTime": HogQLFunctionMeta("UUIDv7ToDateTime", 1, 1, tz_aware=True),
}

# Date conversion functions (that overlap with type conversions)
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
DATE_CONVERSION_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **{
        name: HogQLFunctionMeta(
            "toDateOrNull",
            1,
            1,
            signatures=[
                ((StringType(),), DateType()),
                ((DateTimeType(),), DateType()),
            ],
            # Only the plain constructor takes a number: toDateOrNull expects a String, and rejects a
            # Float with code 43. Integer covers `date - date`, Float `timestamp - timestamp`.
            overloads=[((ast.DateTimeType, ast.DateType, ast.IntegerType, ast.FloatType), "toDate")],
        )
        for name in ["toDate", "to_date"]
    },
    "toDateTime": HogQLFunctionMeta(
        "parseDateTime64BestEffortOrNull",
        1,
        2,
        # Incorrect for parseDateTime64BestEffortOrNull but it is required because when we overload to toDateTime, we use this to figure out if timestamp is already in a function.
        tz_aware=True,
        overloads=[
            # Float covers the `timestamp - timestamp` duration, which the parser cannot take.
            ((ast.DateTimeType, ast.DateType, ast.IntegerType, ast.FloatType), "toDateTime"),
            # ((ast.StringType,), "parseDateTime64"),
        ],
        signatures=[
            ((StringType(),), DateTimeType()),
            ((StringType(), IntegerType()), DateTimeType()),
            ((StringType(), IntegerType(), StringType()), DateTimeType()),
        ],
    ),
    "toDateTime64": HogQLFunctionMeta(
        "toDateTime64",
        1,
        3,
        tz_aware=True,
        signatures=[
            ((DateTimeType(),), DateTimeType()),
            ((DateTimeType(), IntegerType()), DateTimeType()),
            ((DateTimeType(), IntegerType(), StringType()), DateTimeType()),
        ],
    ),
    "toDateTimeUS": HogQLFunctionMeta(
        "parseDateTime64BestEffortUSOrNull",
        1,
        2,
        tz_aware=True,
        signatures=[
            ((StringType(),), DateTimeType()),
            ((StringType(), IntegerType()), DateTimeType()),
            ((StringType(), IntegerType(), StringType()), DateTimeType()),
        ],
    ),
}

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
NULLABILITY_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "isnull": HogQLFunctionMeta("isNull", 1, 1, case_sensitive=False),
    "isNotNull": HogQLFunctionMeta("isNotNull", 1, 1),
    "coalesce": HogQLFunctionMeta("coalesce", 1, None, case_sensitive=False),
    "ifnull": HogQLFunctionMeta(
        "ifNull",
        2,
        2,
        case_sensitive=False,
        signatures=[
            ((StringType(), StringType()), StringType()),
            ((BooleanType(), BooleanType()), BooleanType()),
            ((DateType(), DateType()), DateType()),
            ((DateTimeType(), DateTimeType()), DateTimeType()),
            ((UUIDType(), UUIDType()), UUIDType()),
            ((ArrayType(), ArrayType()), ArrayType()),
            ((DecimalType(), DecimalType()), DecimalType()),
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), FloatType()), FloatType()),
            ((IntervalType(), IntervalType()), IntervalType()),
        ],
    ),
    "nullif": HogQLFunctionMeta(
        "nullIf",
        2,
        2,
        case_sensitive=False,
        signatures=[
            ((StringType(), StringType()), StringType()),
            ((BooleanType(), BooleanType()), BooleanType()),
            ((DateType(), DateType()), DateType()),
            ((DateTimeType(), DateTimeType()), DateTimeType()),
            ((UUIDType(), UUIDType()), UUIDType()),
            ((ArrayType(), ArrayType()), ArrayType()),
            ((DecimalType(), DecimalType()), DecimalType()),
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), FloatType()), FloatType()),
            ((IntervalType(), IntervalType()), IntervalType()),
        ],
    ),
    "assumeNotNull": HogQLFunctionMeta(
        "assumeNotNull",
        1,
        1,
        signatures=[
            ((StringType(),), StringType()),
            ((BooleanType(),), BooleanType()),
            ((DateType(),), DateType()),
            ((DateTimeType(),), DateTimeType()),
            ((UUIDType(),), UUIDType()),
            ((ArrayType(),), ArrayType()),
            ((DecimalType(),), DecimalType()),
            ((IntegerType(),), IntegerType()),
            ((FloatType(),), FloatType()),
            ((IntervalType(),), IntervalType()),
        ],
    ),
    "toNullable": HogQLFunctionMeta(
        "toNullable",
        1,
        1,
        signatures=[
            ((StringType(),), StringType()),
            ((BooleanType(),), BooleanType()),
            ((DateType(),), DateType()),
            ((DateTimeType(),), DateTimeType()),
            ((UUIDType(),), UUIDType()),
            ((ArrayType(),), ArrayType()),
            ((DecimalType(),), DecimalType()),
            ((IntegerType(),), IntegerType()),
            ((FloatType(),), FloatType()),
            ((IntervalType(),), IntervalType()),
        ],
    ),
}

# Combined conversion functions
CONVERSION_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **TYPE_CONVERSION_FUNCTIONS,
    **DATE_CONVERSION_FUNCTIONS,
    **NULLABILITY_FUNCTIONS,
}
