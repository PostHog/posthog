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
    "toInt": HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="Int64")]),
    "toIntOrZero": HogQLFunctionMeta("toInt64OrZero", 1, 1, signatures=[((StringType(),), IntegerType())]),
    "_toInt8": HogQLFunctionMeta("toInt8", 1, 1),
    "_toInt16": HogQLFunctionMeta("toInt16", 1, 1),
    "_toInt32": HogQLFunctionMeta("toInt32", 1, 1),
    "_toInt64": HogQLFunctionMeta("toInt64", 1, 1),
    "_toUInt64": HogQLFunctionMeta("toUInt64", 1, 1, signatures=[((UnknownType(),), IntegerType())]),
    "_toUInt128": HogQLFunctionMeta("toUInt128", 1, 1),
    "toFloat": HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="Float64")]),
    "toFloatOrZero": HogQLFunctionMeta("toFloat64OrZero", 1, 1, signatures=[((StringType(),), FloatType())]),
    "toFloatOrDefault": HogQLFunctionMeta(
        "toFloat64OrDefault",
        1,
        2,
        signatures=[
            ((DecimalType(), FloatType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
            ((FloatType(), FloatType()), FloatType()),
            ((StringType(), FloatType()), FloatType()),
        ],
    ),
    "toDecimal": HogQLFunctionMeta(
        "accurateCastOrNull",
        2,
        2,
        passthrough_suffix_args_count=1,
        suffix_args=[ast.Constant(value="Decimal64({0})")],  # Scale for Decimal64 is customizable
    ),
    "_toDate": HogQLFunctionMeta("toDate", 1, 1),
    "toUUID": HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="UUID")]),
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
    "toBool": HogQLFunctionMeta("toBool", 1, 1),
    "toJSONString": HogQLFunctionMeta("toJSONString", 1, 1),
    "parseDateTime": HogQLFunctionMeta("parseDateTimeOrNull", 2, 3, tz_aware=True),
    "parseDateTimeBestEffort": HogQLFunctionMeta("parseDateTime64BestEffortOrNull", 1, 2, tz_aware=True),
    "toTypeName": HogQLFunctionMeta("toTypeName", 1, 1),
    "cityHash64": HogQLFunctionMeta("cityHash64", 1, 1),
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
            overloads=[((ast.DateTimeType, ast.DateType), "toDate")],
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
            ((ast.DateTimeType, ast.DateType, ast.IntegerType), "toDateTime"),
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
