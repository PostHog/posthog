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

from ..core import HogQLFunctionMeta

# arrays and strings common
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
ARRAY_STRING_COMMON_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "empty": HogQLFunctionMeta(
        "empty",
        1,
        1,
        signatures=[
            ((ArrayType(),), IntegerType()),
            ((StringType(),), IntegerType()),
            ((UUIDType(),), IntegerType()),
        ],
    ),
    "notEmpty": HogQLFunctionMeta(
        "notEmpty",
        1,
        1,
        signatures=[
            ((ArrayType(),), IntegerType()),
            ((StringType(),), IntegerType()),
            ((UUIDType(),), IntegerType()),
        ],
    ),
    "length": HogQLFunctionMeta(
        "length",
        1,
        1,
        case_sensitive=False,
        signatures=[
            ((ArrayType(),), IntegerType()),
            ((StringType(),), IntegerType()),
        ],
    ),
    "reverse": HogQLFunctionMeta("reverse", 1, 1, case_sensitive=False),
}

# arrays
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
ARRAY_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "array": HogQLFunctionMeta("array", 0, None),
    "range": HogQLFunctionMeta("range", 1, 3),
    "arrayConcat": HogQLFunctionMeta("arrayConcat", 2, None),
    "arrayElement": HogQLFunctionMeta("arrayElement", 2, 2),
    "has": HogQLFunctionMeta("has", 2, 2),
    "hasAll": HogQLFunctionMeta("hasAll", 2, 2),
    "hasAny": HogQLFunctionMeta("hasAny", 2, 2),
    "hasSubstr": HogQLFunctionMeta("hasSubstr", 2, 2),
    "indexOf": HogQLFunctionMeta(
        "indexOf",
        2,
        2,
        signatures=[
            (
                (
                    ArrayType(),
                    StringType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    BooleanType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    DateType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    DateTimeType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    UUIDType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    ArrayType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    DecimalType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    IntegerType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    FloatType(),
                ),
                IntegerType(),
            ),
            (
                (
                    ArrayType(),
                    IntervalType(),
                ),
                IntegerType(),
            ),
        ],
    ),
    "arrayCount": HogQLFunctionMeta("arrayCount", 1, None),
    "countEqual": HogQLFunctionMeta("countEqual", 2, 2),
    "arrayEnumerate": HogQLFunctionMeta("arrayEnumerate", 1, 1),
    "arrayEnumerateUniq": HogQLFunctionMeta("arrayEnumerateUniq", 2, None),
    "arrayPopBack": HogQLFunctionMeta("arrayPopBack", 1, 1),
    "arrayPopFront": HogQLFunctionMeta("arrayPopFront", 1, 1),
    "arrayPushBack": HogQLFunctionMeta("arrayPushBack", 2, 2),
    "arrayPushFront": HogQLFunctionMeta("arrayPushFront", 2, 2),
    "arrayResize": HogQLFunctionMeta("arrayResize", 2, 3),
    "arraySlice": HogQLFunctionMeta("arraySlice", 2, 3),
    "arraySort": HogQLFunctionMeta("arraySort", 1, None),
    "arrayReverseSort": HogQLFunctionMeta("arraySort", 1, None),
    "arrayUniq": HogQLFunctionMeta("arrayUniq", 1, None),
    "arrayJoin": HogQLFunctionMeta("arrayJoin", 1, 1),
    "arrayDifference": HogQLFunctionMeta("arrayDifference", 1, 1),
    "arrayDistinct": HogQLFunctionMeta("arrayDistinct", 1, 1),
    "arrayEnumerateDense": HogQLFunctionMeta("arrayEnumerateDense", 1, 1),
    "arrayIntersect": HogQLFunctionMeta("arrayIntersect", 1, None),
    "arrayReduce": HogQLFunctionMeta("arrayReduce", 2, None, parametric_first_arg=True),
    # "arrayReduceInRanges": HogQLFunctionMeta("arrayReduceInRanges", 3,None),  # takes a "parametric function" as first arg, is that safe?
    "arrayReverse": HogQLFunctionMeta("arrayReverse", 1, 1),
    "arrayFilter": HogQLFunctionMeta("arrayFilter", 2, None),
    "arrayFlatten": HogQLFunctionMeta("arrayFlatten", 1, 1),
    "arrayCompact": HogQLFunctionMeta("arrayCompact", 1, 1),
    "arrayZip": HogQLFunctionMeta("arrayZip", 2, None),
    "arrayAUC": HogQLFunctionMeta("arrayAUC", 2, 2),
    "arrayMap": HogQLFunctionMeta("arrayMap", 2, None),
    "arrayFill": HogQLFunctionMeta("arrayFill", 2, None),
    "arrayFold": HogQLFunctionMeta("arrayFold", 3, None),
    "arrayWithConstant": HogQLFunctionMeta("arrayWithConstant", 2, 2),
    "arraySplit": HogQLFunctionMeta("arraySplit", 2, None),
    "arrayReverseFill": HogQLFunctionMeta("arrayReverseFill", 2, None),
    "arrayReverseSplit": HogQLFunctionMeta("arrayReverseSplit", 2, None),
    "arrayRotateLeft": HogQLFunctionMeta("arrayRotateLeft", 2, 2),
    "arrayRotateRight": HogQLFunctionMeta("arrayRotateRight", 2, 2),
    "arrayExists": HogQLFunctionMeta("arrayExists", 1, None),
    "arrayAll": HogQLFunctionMeta("arrayAll", 1, None),
    "arrayFirst": HogQLFunctionMeta("arrayFirst", 2, None),
    "arrayLast": HogQLFunctionMeta("arrayLast", 2, None),
    "arrayFirstIndex": HogQLFunctionMeta("arrayFirstIndex", 2, None),
    "arrayLastIndex": HogQLFunctionMeta("arrayLastIndex", 2, None),
    "arrayMin": HogQLFunctionMeta("arrayMin", 1, 2),
    "arrayMax": HogQLFunctionMeta("arrayMax", 1, 2),
    "arraySum": HogQLFunctionMeta("arraySum", 1, 2),
    "arrayAvg": HogQLFunctionMeta("arrayAvg", 1, 2),
    "arrayCumSum": HogQLFunctionMeta("arrayCumSum", 1, None),
    "arrayCumSumNonNegative": HogQLFunctionMeta("arrayCumSumNonNegative", 1, None),
    "arrayProduct": HogQLFunctionMeta("arrayProduct", 1, 1),
    "arrayStringConcat": HogQLFunctionMeta("arrayStringConcat", 1, 2),
    # table functions
    "generateSeries": HogQLFunctionMeta("generate_series", 3, 3),
}

# Combined arrays and strings functions
ARRAYS_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **ARRAY_STRING_COMMON_FUNCTIONS,
    **ARRAY_FUNCTIONS,
}
