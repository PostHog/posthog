from dataclasses import dataclass
from itertools import chain
from typing import Optional


from posthog.cloud_utils import is_cloud, is_ci
from posthog.hogql import ast
from posthog.hogql.ast import (
    ArrayType,
    BooleanType,
    DateTimeType,
    DateType,
    FloatType,
    IntervalType,
    StringType,
    TupleType,
    IntegerType,
    DecimalType,
    UUIDType,
)
from posthog.hogql.base import ConstantType, UnknownType
from posthog.hogql.errors import QueryError


def validate_function_args(
    args: list[ast.Expr],
    min_args: int,
    max_args: Optional[int],
    function_name: str,
    *,
    function_term="function",
    argument_term="argument",
):
    too_few = len(args) < min_args
    too_many = max_args is not None and len(args) > max_args
    if min_args == max_args and (too_few or too_many):
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects {min_args} {argument_term}{'s' if min_args != 1 else ''}, found {len(args)}"
        )
    if too_few:
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects at least {min_args} {argument_term}{'s' if min_args != 1 else ''}, found {len(args)}"
        )
    if too_many:
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects at most {max_args} {argument_term}{'s' if max_args != 1 else ''}, found {len(args)}"
        )


Overload = tuple[tuple[type[ConstantType], ...] | type[ConstantType], str]
AnyConstantType = (
    StringType
    | BooleanType
    | DateType
    | DateTimeType
    | UUIDType
    | ArrayType
    | TupleType
    | DecimalType
    | UnknownType
    | IntegerType
    | FloatType
    | IntervalType
)


@dataclass()
class HogQLFunctionMeta:
    clickhouse_name: str
    min_args: int = 0
    max_args: Optional[int] = 0
    min_params: int = 0
    max_params: Optional[int] = 0
    passthrough_suffix_args_count: int = 0
    aggregate: bool = False
    overloads: Optional[list[Overload]] = None
    """Overloads allow for using a different ClickHouse function depending on the type of the first arg."""
    tz_aware: bool = False
    """Whether the function is timezone-aware. This means the project timezone will be appended as the last arg."""
    case_sensitive: bool = True
    """Not all ClickHouse functions are case-insensitive. See https://clickhouse.com/docs/en/sql-reference/syntax#keywords."""
    signatures: Optional[list[tuple[tuple[AnyConstantType, ...], AnyConstantType]]] = None
    """Signatures allow for specifying the types of the arguments and the return type of the function."""
    suffix_args: Optional[list[ast.Constant]] = None
    """Additional arguments that are added to the end of the arguments provided by the caller"""
    using_placeholder_arguments: bool = False
    using_positional_arguments: bool = False
    parametric_first_arg: bool = False
    """Some ClickHouse functions take a constant string function name as the first argument. Check that it's one of our allowed function names."""


def compare_types(arg_types: list[ConstantType], sig_arg_types: tuple[ConstantType, ...]):
    if len(arg_types) != len(sig_arg_types):
        return False

    return all(
        isinstance(sig_arg_type, UnknownType) or isinstance(arg_type, sig_arg_type.__class__)
        for arg_type, sig_arg_type in zip(arg_types, sig_arg_types)
    )


HOGQL_COMPARISON_MAPPING: dict[str, ast.CompareOperationOp] = {
    "equals": ast.CompareOperationOp.Eq,
    "notEquals": ast.CompareOperationOp.NotEq,
    "less": ast.CompareOperationOp.Lt,
    "greater": ast.CompareOperationOp.Gt,
    "lessOrEquals": ast.CompareOperationOp.LtEq,
    "greaterOrEquals": ast.CompareOperationOp.GtEq,
    "like": ast.CompareOperationOp.Like,
    "ilike": ast.CompareOperationOp.ILike,
    "notLike": ast.CompareOperationOp.NotLike,
    "notILike": ast.CompareOperationOp.NotILike,
    "in": ast.CompareOperationOp.In,
    "notIn": ast.CompareOperationOp.NotIn,
}

HOGQL_CLICKHOUSE_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    # arithmetic
    "plus": HogQLFunctionMeta(
        "plus",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
            (
                (
                    TupleType(item_types=[IntegerType()], repeat=True),
                    TupleType(item_types=[IntegerType()], repeat=True),
                ),
                TupleType(item_types=[IntegerType()], repeat=True),
            ),
            ((DateTimeType(), IntegerType()), DateTimeType()),
            ((IntegerType(), DateTimeType()), DateTimeType()),
            ((DateTimeType(), IntervalType()), DateTimeType()),
            ((IntervalType(), DateTimeType()), DateTimeType()),
        ],
    ),
    "minus": HogQLFunctionMeta(
        "minus",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
            (
                (
                    TupleType(item_types=[IntegerType()], repeat=True),
                    TupleType(item_types=[IntegerType()], repeat=True),
                ),
                TupleType(item_types=[IntegerType()], repeat=True),
            ),
            ((DateTimeType(), IntegerType()), DateTimeType()),
            ((IntegerType(), DateTimeType()), DateTimeType()),
            ((DateTimeType(), IntervalType()), DateTimeType()),
            ((IntervalType(), DateTimeType()), DateTimeType()),
        ],
    ),
    "multiply": HogQLFunctionMeta(
        "multiply",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
            (
                (
                    TupleType(item_types=[IntegerType()], repeat=True),
                    TupleType(item_types=[IntegerType()], repeat=True),
                ),
                TupleType(item_types=[IntegerType()], repeat=True),
            ),
            (
                (IntegerType(), TupleType(item_types=[IntegerType()], repeat=True)),
                TupleType(item_types=[IntegerType()], repeat=True),
            ),
            (
                (TupleType(item_types=[IntegerType()], repeat=True), IntegerType()),
                TupleType(item_types=[IntegerType()], repeat=True),
            ),
            ((DateTimeType(), IntegerType()), DateTimeType()),
            ((IntegerType(), DateTimeType()), DateTimeType()),
        ],
    ),
    "divide": HogQLFunctionMeta(
        "divide",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
            (
                (TupleType(item_types=[IntegerType()], repeat=True), IntegerType()),
                TupleType(item_types=[IntegerType()], repeat=True),
            ),
            ((DateTimeType(), IntegerType()), DateTimeType()),
            ((IntegerType(), DateTimeType()), DateTimeType()),
        ],
    ),
    "intDiv": HogQLFunctionMeta(
        "intDiv",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "intDivOrZero": HogQLFunctionMeta(
        "intDivOrZero",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "modulo": HogQLFunctionMeta(
        "modulo",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
        ],
    ),
    "moduloOrZero": HogQLFunctionMeta(
        "moduloOrZero",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
        ],
    ),
    "positiveModulo": HogQLFunctionMeta(
        "positiveModulo",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
        ],
    ),
    "negate": HogQLFunctionMeta(
        "negate",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
            ((FloatType(),), FloatType()),
            ((DecimalType(),), DecimalType()),
        ],
    ),
    "abs": HogQLFunctionMeta(
        "abs",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
        case_sensitive=False,
    ),
    "gcd": HogQLFunctionMeta(
        "gcd",
        2,
        2,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "lcm": HogQLFunctionMeta(
        "lcm",
        2,
        2,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "max2": HogQLFunctionMeta(
        "max2",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), FloatType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
        ],
        case_sensitive=False,
    ),
    "min2": HogQLFunctionMeta(
        "min2",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), FloatType()),
            ((FloatType(), IntegerType()), FloatType()),
            ((IntegerType(), FloatType()), FloatType()),
        ],
        case_sensitive=False,
    ),
    "multiplyDecimal": HogQLFunctionMeta("multiplyDecimal", 2, 3),
    "divideDecimal": HogQLFunctionMeta("divideDecimal", 2, 3),
    # arrays and strings common
    "empty": HogQLFunctionMeta("empty", 1, 1),
    "notEmpty": HogQLFunctionMeta("notEmpty", 1, 1),
    "length": HogQLFunctionMeta("length", 1, 1, case_sensitive=False),
    "reverse": HogQLFunctionMeta("reverse", 1, 1, case_sensitive=False),
    # arrays
    "array": HogQLFunctionMeta("array", 0, None),
    "range": HogQLFunctionMeta("range", 1, 3),
    "arrayConcat": HogQLFunctionMeta("arrayConcat", 2, None),
    "arrayElement": HogQLFunctionMeta("arrayElement", 2, 2),
    "has": HogQLFunctionMeta("has", 2, 2),
    "hasAll": HogQLFunctionMeta("hasAll", 2, 2),
    "hasAny": HogQLFunctionMeta("hasAny", 2, 2),
    "hasSubstr": HogQLFunctionMeta("hasSubstr", 2, 2),
    "indexOf": HogQLFunctionMeta("indexOf", 2, 2),
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
    # comparison
    "equals": HogQLFunctionMeta("equals", 2, 2),
    "notEquals": HogQLFunctionMeta("notEquals", 2, 2),
    "less": HogQLFunctionMeta("less", 2, 2),
    "greater": HogQLFunctionMeta("greater", 2, 2),
    "lessOrEquals": HogQLFunctionMeta("lessOrEquals", 2, 2),
    "greaterOrEquals": HogQLFunctionMeta("greaterOrEquals", 2, 2),
    # logical
    "and": HogQLFunctionMeta("and", 2, None),
    "or": HogQLFunctionMeta("or", 2, None),
    "xor": HogQLFunctionMeta("xor", 2, None),
    "not": HogQLFunctionMeta("not", 1, 1, case_sensitive=False),
    # type conversions
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
    "_toInt8": HogQLFunctionMeta("toInt8", 1, 1),
    "_toInt16": HogQLFunctionMeta("toInt16", 1, 1),
    "_toInt32": HogQLFunctionMeta("toInt32", 1, 1),
    "_toInt64": HogQLFunctionMeta("toInt64", 1, 1),
    "_toUInt64": HogQLFunctionMeta("toUInt64", 1, 1, signatures=[((UnknownType(),), IntegerType())]),
    "_toUInt128": HogQLFunctionMeta("toUInt128", 1, 1),
    "toFloat": HogQLFunctionMeta("accurateCastOrNull", 1, 1, suffix_args=[ast.Constant(value="Float64")]),
    "toDecimal": HogQLFunctionMeta(
        "accurateCastOrNull",
        2,
        2,
        passthrough_suffix_args_count=1,
        suffix_args=[ast.Constant(value="Decimal64({0})")],  # Scale for Decimal64 is customizable
    ),
    "_toDate": HogQLFunctionMeta("toDate", 1, 1),
    **{
        name: HogQLFunctionMeta(
            "toDateOrNull",
            1,
            1,
            overloads=[((ast.DateTimeType, ast.DateType), "toDate")],
        )
        for name in ["toDate", "to_date"]
    },
    "toDateTime": HogQLFunctionMeta(
        "parseDateTime64BestEffortOrNull",
        1,
        2,  # Incorrect for parseDateTime64BestEffortOrNull but it is required because when we overload to toDateTime, we use this to figure out if timestamp is already in a function.
        tz_aware=True,
        overloads=[
            ((ast.DateTimeType, ast.DateType, ast.IntegerType), "toDateTime"),
            # ((ast.StringType,), "parseDateTime64"), # missing in version: 24.8.7.41
        ],
        signatures=[
            ((StringType(),), DateTimeType()),
            ((StringType(), IntegerType()), DateTimeType()),
            ((StringType(), IntegerType(), StringType()), DateTimeType()),
        ],
    ),
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
    # dates and times
    "timeZoneOf": HogQLFunctionMeta("timeZoneOf", 1, 1),
    "timeZoneOffset": HogQLFunctionMeta("timeZoneOffset", 1, 1),
    "toYear": HogQLFunctionMeta("toYear", 1, 1),
    "toQuarter": HogQLFunctionMeta("toQuarter", 1, 1),
    "toMonth": HogQLFunctionMeta("toMonth", 1, 1),
    "toDayOfYear": HogQLFunctionMeta("toDayOfYear", 1, 1),
    "toDayOfMonth": HogQLFunctionMeta("toDayOfMonth", 1, 1),
    "toDayOfWeek": HogQLFunctionMeta("toDayOfWeek", 1, 3),
    "toHour": HogQLFunctionMeta("toHour", 1, 1),
    "toMinute": HogQLFunctionMeta("toMinute", 1, 1),
    "toSecond": HogQLFunctionMeta("toSecond", 1, 1),
    "toUnixTimestamp": HogQLFunctionMeta("toUnixTimestamp", 1, 2),
    "toUnixTimestamp64Milli": HogQLFunctionMeta("toUnixTimestamp64Milli", 1, 1),
    "toStartOfInterval": HogQLFunctionMeta("toStartOfInterval", 2, 2),
    "toStartOfYear": HogQLFunctionMeta("toStartOfYear", 1, 1),
    "toStartOfISOYear": HogQLFunctionMeta("toStartOfISOYear", 1, 1),
    "toStartOfQuarter": HogQLFunctionMeta("toStartOfQuarter", 1, 1),
    "toStartOfMonth": HogQLFunctionMeta(
        "toStartOfMonth",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateType()),
        ],
    ),
    "toLastDayOfMonth": HogQLFunctionMeta("toLastDayOfMonth", 1, 1),
    "toMonday": HogQLFunctionMeta("toMonday", 1, 1),
    "toStartOfWeek": HogQLFunctionMeta(
        "toStartOfWeek",
        1,
        2,
        signatures=[
            ((UnknownType(),), DateType()),
            ((UnknownType(), UnknownType()), DateType()),
        ],
    ),
    "toStartOfDay": HogQLFunctionMeta(
        "toStartOfDay",
        1,
        2,
        signatures=[
            ((UnknownType(),), DateTimeType()),
            ((UnknownType(), UnknownType()), DateTimeType()),
        ],
    ),
    "toLastDayOfWeek": HogQLFunctionMeta("toLastDayOfWeek", 1, 2),
    "toStartOfHour": HogQLFunctionMeta(
        "toStartOfHour",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "toStartOfMinute": HogQLFunctionMeta(
        "toStartOfMinute",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "toStartOfSecond": HogQLFunctionMeta(
        "toStartOfSecond",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "toStartOfFiveMinutes": HogQLFunctionMeta("toStartOfFiveMinutes", 1, 1),
    "toStartOfTenMinutes": HogQLFunctionMeta("toStartOfTenMinutes", 1, 1),
    "toStartOfFifteenMinutes": HogQLFunctionMeta("toStartOfFifteenMinutes", 1, 1),
    "toTime": HogQLFunctionMeta("toTime", 1, 1),
    "toISOYear": HogQLFunctionMeta("toISOYear", 1, 1),
    "toISOWeek": HogQLFunctionMeta("toISOWeek", 1, 1),
    "toWeek": HogQLFunctionMeta("toWeek", 1, 3),
    "toYearWeek": HogQLFunctionMeta("toYearWeek", 1, 3),
    "age": HogQLFunctionMeta("age", 3, 3),
    "dateAdd": HogQLFunctionMeta(
        "dateAdd",
        2,
        3,
        signatures=[
            ((DateType(), UnknownType()), DateType()),
            ((StringType(), UnknownType(), DateType()), DateType()),
        ],
    ),
    "dateSub": HogQLFunctionMeta(
        "dateSub",
        2,
        3,
        signatures=[
            ((DateType(), UnknownType()), DateType()),
            ((StringType(), UnknownType(), DateType()), DateType()),
        ],
    ),
    "timeStampAdd": HogQLFunctionMeta("timeStampAdd", 2, 2),
    "timeStampSub": HogQLFunctionMeta("timeStampSub", 2, 2),
    "nowInBlock": HogQLFunctionMeta("nowInBlock", 1, 1),
    "rowNumberInBlock": HogQLFunctionMeta("rowNumberInBlock", 0, 0),
    "rowNumberInAllBlocks": HogQLFunctionMeta("rowNumberInAllBlocks", 0, 0),
    "yesterday": HogQLFunctionMeta("yesterday"),
    "timeSlot": HogQLFunctionMeta("timeSlot", 1, 1),
    "toYYYYMM": HogQLFunctionMeta("toYYYYMM", 1, 1),
    "toYYYYMMDD": HogQLFunctionMeta("toYYYYMMDD", 1, 1),
    "toYYYYMMDDhhmmss": HogQLFunctionMeta("toYYYYMMDDhhmmss", 1, 1),
    "addYears": HogQLFunctionMeta("addYears", 2, 2),
    "addMonths": HogQLFunctionMeta("addMonths", 2, 2),
    "addWeeks": HogQLFunctionMeta("addWeeks", 2, 2),
    "addDays": HogQLFunctionMeta("addDays", 2, 2),
    "addHours": HogQLFunctionMeta("addHours", 2, 2),
    "addMinutes": HogQLFunctionMeta("addMinutes", 2, 2),
    "addSeconds": HogQLFunctionMeta("addSeconds", 2, 2),
    "addQuarters": HogQLFunctionMeta("addQuarters", 2, 2),
    "subtractYears": HogQLFunctionMeta("subtractYears", 2, 2),
    "subtractMonths": HogQLFunctionMeta("subtractMonths", 2, 2),
    "subtractWeeks": HogQLFunctionMeta("subtractWeeks", 2, 2),
    "subtractDays": HogQLFunctionMeta("subtractDays", 2, 2),
    "subtractHours": HogQLFunctionMeta("subtractHours", 2, 2),
    "subtractMinutes": HogQLFunctionMeta("subtractMinutes", 2, 2),
    "subtractSeconds": HogQLFunctionMeta("subtractSeconds", 2, 2),
    "subtractQuarters": HogQLFunctionMeta("subtractQuarters", 2, 2),
    "timeSlots": HogQLFunctionMeta("timeSlots", 2, 3),
    "formatDateTime": HogQLFunctionMeta("formatDateTime", 2, 3),
    "dateName": HogQLFunctionMeta("dateName", 2, 2),
    "monthName": HogQLFunctionMeta("monthName", 1, 1),
    "fromUnixTimestamp": HogQLFunctionMeta(
        "fromUnixTimestamp",
        1,
        1,
        signatures=[
            ((IntegerType(),), DateTimeType()),
        ],
    ),
    "toModifiedJulianDay": HogQLFunctionMeta("toModifiedJulianDayOrNull", 1, 1),
    "fromModifiedJulianDay": HogQLFunctionMeta("fromModifiedJulianDayOrNull", 1, 1),
    "toIntervalSecond": HogQLFunctionMeta(
        "toIntervalSecond",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalMinute": HogQLFunctionMeta(
        "toIntervalMinute",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalHour": HogQLFunctionMeta(
        "toIntervalHour",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalDay": HogQLFunctionMeta(
        "toIntervalDay",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalWeek": HogQLFunctionMeta(
        "toIntervalWeek",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalMonth": HogQLFunctionMeta(
        "toIntervalMonth",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalQuarter": HogQLFunctionMeta(
        "toIntervalQuarter",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalYear": HogQLFunctionMeta(
        "toIntervalYear",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    # strings
    "left": HogQLFunctionMeta("left", 2, 2, signatures=[((StringType(), IntegerType()), StringType())]),
    "right": HogQLFunctionMeta("right", 2, 2, signatures=[((StringType(), IntegerType()), StringType())]),
    "lengthUTF8": HogQLFunctionMeta("lengthUTF8", 1, 1),
    "leftPad": HogQLFunctionMeta("leftPad", 2, 3),
    "rightPad": HogQLFunctionMeta("rightPad", 2, 3),
    "leftPadUTF8": HogQLFunctionMeta("leftPadUTF8", 2, 3),
    "rightPadUTF8": HogQLFunctionMeta("rightPadUTF8", 2, 3),
    "lower": HogQLFunctionMeta("lower", 1, 1, case_sensitive=False),
    "upper": HogQLFunctionMeta("upper", 1, 1, case_sensitive=False),
    "lowerUTF8": HogQLFunctionMeta("lowerUTF8", 1, 1),
    "upperUTF8": HogQLFunctionMeta("upperUTF8", 1, 1),
    "isValidUTF8": HogQLFunctionMeta("isValidUTF8", 1, 1),
    "toValidUTF8": HogQLFunctionMeta("toValidUTF8", 1, 1),
    "repeat": HogQLFunctionMeta("repeat", 2, 2, case_sensitive=False),
    "format": HogQLFunctionMeta("format", 2, None),
    "reverseUTF8": HogQLFunctionMeta("reverseUTF8", 1, 1),
    "concat": HogQLFunctionMeta("concat", 2, None, case_sensitive=False),
    "substring": HogQLFunctionMeta("substring", 3, 3, case_sensitive=False),
    "substringUTF8": HogQLFunctionMeta("substringUTF8", 3, 3),
    "appendTrailingCharIfAbsent": HogQLFunctionMeta("appendTrailingCharIfAbsent", 2, 2),
    "convertCharset": HogQLFunctionMeta("convertCharset", 3, 3),
    "base58Encode": HogQLFunctionMeta("base58Encode", 1, 1),
    "base58Decode": HogQLFunctionMeta("base58Decode", 1, 1),
    "tryBase58Decode": HogQLFunctionMeta("tryBase58Decode", 1, 1),
    "base64Encode": HogQLFunctionMeta("base64Encode", 1, 1),
    "base64Decode": HogQLFunctionMeta("base64Decode", 1, 1),
    "tryBase64Decode": HogQLFunctionMeta("tryBase64Decode", 1, 1),
    "endsWith": HogQLFunctionMeta("endsWith", 2, 2),
    "startsWith": HogQLFunctionMeta("startsWith", 2, 2),
    "encodeXMLComponent": HogQLFunctionMeta("encodeXMLComponent", 1, 1),
    "decodeXMLComponent": HogQLFunctionMeta("decodeXMLComponent", 1, 1),
    "extractTextFromHTML": HogQLFunctionMeta("extractTextFromHTML", 1, 1),
    "ascii": HogQLFunctionMeta("ascii", 1, 1, case_sensitive=False),
    "concatWithSeparator": HogQLFunctionMeta("concatWithSeparator", 2, None),
    # searching in strings
    "position": HogQLFunctionMeta("position", 2, 3, case_sensitive=False),
    "positionCaseInsensitive": HogQLFunctionMeta("positionCaseInsensitive", 2, 3),
    "positionUTF8": HogQLFunctionMeta("positionUTF8", 2, 3),
    "positionCaseInsensitiveUTF8": HogQLFunctionMeta("positionCaseInsensitiveUTF8", 2, 3),
    "multiSearchAllPositions": HogQLFunctionMeta("multiSearchAllPositions", 2, 2),
    "multiSearchAllPositionsUTF8": HogQLFunctionMeta("multiSearchAllPositionsUTF8", 2, 2),
    "multiSearchFirstPosition": HogQLFunctionMeta("multiSearchFirstPosition", 2, 2),
    "multiSearchFirstIndex": HogQLFunctionMeta("multiSearchFirstIndex", 2, 2),
    "multiSearchAny": HogQLFunctionMeta("multiSearchAny", 2, 2),
    "match": HogQLFunctionMeta("match", 2, 2),
    "multiMatchAny": HogQLFunctionMeta("multiMatchAny", 2, 2),
    "multiMatchAnyIndex": HogQLFunctionMeta("multiMatchAnyIndex", 2, 2),
    "multiMatchAllIndices": HogQLFunctionMeta("multiMatchAllIndices", 2, 2),
    "multiFuzzyMatchAny": HogQLFunctionMeta("multiFuzzyMatchAny", 3, 3),
    "multiFuzzyMatchAnyIndex": HogQLFunctionMeta("multiFuzzyMatchAnyIndex", 3, 3),
    "multiFuzzyMatchAllIndices": HogQLFunctionMeta("multiFuzzyMatchAllIndices", 3, 3),
    "extract": HogQLFunctionMeta("extract", 2, 2, case_sensitive=False),
    "extractAll": HogQLFunctionMeta("extractAll", 2, 2),
    "extractAllGroupsHorizontal": HogQLFunctionMeta("extractAllGroupsHorizontal", 2, 2),
    "extractAllGroupsVertical": HogQLFunctionMeta("extractAllGroupsVertical", 2, 2),
    "like": HogQLFunctionMeta("like", 2, 2),
    "ilike": HogQLFunctionMeta("ilike", 2, 2),
    "notLike": HogQLFunctionMeta("notLike", 2, 2),
    "notILike": HogQLFunctionMeta("notILike", 2, 2),
    "ngramDistance": HogQLFunctionMeta("ngramDistance", 2, 2),
    "ngramSearch": HogQLFunctionMeta("ngramSearch", 2, 2),
    "countSubstrings": HogQLFunctionMeta("countSubstrings", 2, 3),
    "countSubstringsCaseInsensitive": HogQLFunctionMeta("countSubstringsCaseInsensitive", 2, 3),
    "countSubstringsCaseInsensitiveUTF8": HogQLFunctionMeta("countSubstringsCaseInsensitiveUTF8", 2, 3),
    "countMatches": HogQLFunctionMeta("countMatches", 2, 2),
    "regexpExtract": HogQLFunctionMeta("regexpExtract", 2, 3),
    # replacing in strings
    "replace": HogQLFunctionMeta("replace", 3, 3, case_sensitive=False),
    "replaceAll": HogQLFunctionMeta("replaceAll", 3, 3),
    "replaceOne": HogQLFunctionMeta("replaceOne", 3, 3),
    "replaceRegexpAll": HogQLFunctionMeta("replaceRegexpAll", 3, 3),
    "replaceRegexpOne": HogQLFunctionMeta("replaceRegexpOne", 3, 3),
    "regexpQuoteMeta": HogQLFunctionMeta("regexpQuoteMeta", 1, 1),
    "translate": HogQLFunctionMeta("translate", 3, 3),
    "translateUTF8": HogQLFunctionMeta("translateUTF8", 3, 3),
    # conditional
    "if": HogQLFunctionMeta("if", 3, 3, case_sensitive=False),
    "multiIf": HogQLFunctionMeta("multiIf", 3, None),
    # mathematical
    "e": HogQLFunctionMeta("e"),
    "pi": HogQLFunctionMeta("pi"),
    "exp": HogQLFunctionMeta("exp", 1, 1, case_sensitive=False),
    "log": HogQLFunctionMeta("log", 1, 1, case_sensitive=False),
    "ln": HogQLFunctionMeta("ln", 1, 1, case_sensitive=False),
    "exp2": HogQLFunctionMeta("exp2", 1, 1),
    "log2": HogQLFunctionMeta("log2", 1, 1, case_sensitive=False),
    "exp10": HogQLFunctionMeta("exp10", 1, 1),
    "log10": HogQLFunctionMeta("log10", 1, 1, case_sensitive=False),
    "sqrt": HogQLFunctionMeta("sqrt", 1, 1, case_sensitive=False),
    "cbrt": HogQLFunctionMeta("cbrt", 1, 1),
    "erf": HogQLFunctionMeta("erf", 1, 1),
    "erfc": HogQLFunctionMeta("erfc", 1, 1),
    "lgamma": HogQLFunctionMeta("lgamma", 1, 1),
    "tgamma": HogQLFunctionMeta("tgamma", 1, 1),
    "sin": HogQLFunctionMeta("sin", 1, 1, case_sensitive=False),
    "cos": HogQLFunctionMeta("cos", 1, 1, case_sensitive=False),
    "tan": HogQLFunctionMeta("tan", 1, 1, case_sensitive=False),
    "asin": HogQLFunctionMeta("asin", 1, 1, case_sensitive=False),
    "acos": HogQLFunctionMeta("acos", 1, 1, case_sensitive=False),
    "atan": HogQLFunctionMeta("atan", 1, 1, case_sensitive=False),
    "pow": HogQLFunctionMeta("pow", 2, 2, case_sensitive=False),
    "power": HogQLFunctionMeta("power", 2, 2, case_sensitive=False),
    "intExp2": HogQLFunctionMeta("intExp2", 1, 1),
    "intExp10": HogQLFunctionMeta("intExp10", 1, 1),
    "cosh": HogQLFunctionMeta("cosh", 1, 1),
    "acosh": HogQLFunctionMeta("acosh", 1, 1),
    "sinh": HogQLFunctionMeta("sinh", 1, 1),
    "asinh": HogQLFunctionMeta("asinh", 1, 1),
    "atanh": HogQLFunctionMeta("atanh", 1, 1),
    "atan2": HogQLFunctionMeta("atan2", 2, 2),
    "hypot": HogQLFunctionMeta("hypot", 2, 2),
    "log1p": HogQLFunctionMeta("log1p", 1, 1),
    "sign": HogQLFunctionMeta("sign", 1, 1, case_sensitive=False),
    "degrees": HogQLFunctionMeta("degrees", 1, 1, case_sensitive=False),
    "radians": HogQLFunctionMeta("radians", 1, 1, case_sensitive=False),
    "factorial": HogQLFunctionMeta("factorial", 1, 1, case_sensitive=False),
    "width_bucket": HogQLFunctionMeta("width_bucket", 4, 4),
    # rounding
    "floor": HogQLFunctionMeta("floor", 1, 2, case_sensitive=False),
    "ceil": HogQLFunctionMeta("ceil", 1, 2, case_sensitive=False),
    "trunc": HogQLFunctionMeta("trunc", 1, 2, case_sensitive=False),
    "round": HogQLFunctionMeta("round", 1, 2, case_sensitive=False),
    "roundBankers": HogQLFunctionMeta("roundBankers", 1, 2),
    "roundToExp2": HogQLFunctionMeta("roundToExp2", 1, 1),
    "roundDuration": HogQLFunctionMeta("roundDuration", 1, 1),
    "roundAge": HogQLFunctionMeta("roundAge", 1, 1),
    "roundDown": HogQLFunctionMeta("roundDown", 2, 2),
    # maps
    "map": HogQLFunctionMeta("map", 0, None),
    "mapFromArrays": HogQLFunctionMeta("mapFromArrays", 2, 2),
    "mapAdd": HogQLFunctionMeta("mapAdd", 2, None),
    "mapSubtract": HogQLFunctionMeta("mapSubtract", 2, None),
    "mapPopulateSeries": HogQLFunctionMeta("mapPopulateSeries", 1, 3),
    "mapContains": HogQLFunctionMeta("mapContains", 2, 2),
    "mapKeys": HogQLFunctionMeta("mapKeys", 1, 1),
    "mapValues": HogQLFunctionMeta("mapValues", 1, 1),
    "mapContainsKeyLike": HogQLFunctionMeta("mapContainsKeyLike", 2, 2),
    "mapExtractKeyLike": HogQLFunctionMeta("mapExtractKeyLike", 2, 2),
    "mapApply": HogQLFunctionMeta("mapApply", 2, 2),
    "mapFilter": HogQLFunctionMeta("mapFilter", 2, 2),
    "mapUpdate": HogQLFunctionMeta("mapUpdate", 2, 2),
    # splitting strings
    "splitByChar": HogQLFunctionMeta("splitByChar", 2, 3),
    "splitByString": HogQLFunctionMeta("splitByString", 2, 3),
    "splitByRegexp": HogQLFunctionMeta("splitByRegexp", 2, 3),
    "splitByWhitespace": HogQLFunctionMeta("splitByWhitespace", 1, 2),
    "splitByNonAlpha": HogQLFunctionMeta("splitByNonAlpha", 1, 2),
    "arrayStringConcat": HogQLFunctionMeta("arrayStringConcat", 1, 2),
    "alphaTokens": HogQLFunctionMeta("alphaTokens", 1, 2),
    "extractAllGroups": HogQLFunctionMeta("extractAllGroups", 2, 2),
    "ngrams": HogQLFunctionMeta("ngrams", 2, 2),
    "tokens": HogQLFunctionMeta("tokens", 1, 1),
    # bit
    "bitAnd": HogQLFunctionMeta("bitAnd", 2, 2),
    "bitOr": HogQLFunctionMeta("bitOr", 2, 2),
    "bitXor": HogQLFunctionMeta("bitXor", 2, 2),
    "bitNot": HogQLFunctionMeta("bitNot", 1, 1),
    "bitShiftLeft": HogQLFunctionMeta("bitShiftLeft", 2, 2),
    "bitShiftRight": HogQLFunctionMeta("bitShiftRight", 2, 2),
    "bitRotateLeft": HogQLFunctionMeta("bitRotateLeft", 2, 2),
    "bitRotateRight": HogQLFunctionMeta("bitRotateRight", 2, 2),
    "bitSlice": HogQLFunctionMeta("bitSlice", 3, 3),
    "bitTest": HogQLFunctionMeta("bitTest", 2, 2),
    "bitTestAll": HogQLFunctionMeta("bitTestAll", 3, None),
    "bitTestAny": HogQLFunctionMeta("bitTestAny", 3, None),
    "bitCount": HogQLFunctionMeta("bitCount", 1, 1),
    "bitHammingDistance": HogQLFunctionMeta("bitHammingDistance", 2, 2),
    # bitmap
    "bitmapBuild": HogQLFunctionMeta("bitmapBuild", 1, 1),
    "bitmapToArray": HogQLFunctionMeta("bitmapToArray", 1, 1),
    "bitmapSubsetInRange": HogQLFunctionMeta("bitmapSubsetInRange", 3, 3),
    "bitmapSubsetLimit": HogQLFunctionMeta("bitmapSubsetLimit", 3, 3),
    "subBitmap": HogQLFunctionMeta("subBitmap", 3, 3),
    "bitmapContains": HogQLFunctionMeta("bitmapContains", 2, 2),
    "bitmapHasAny": HogQLFunctionMeta("bitmapHasAny", 2, 2),
    "bitmapHasAll": HogQLFunctionMeta("bitmapHasAll", 2, 2),
    "bitmapCardinality": HogQLFunctionMeta("bitmapCardinality", 1, 1),
    "bitmapMin": HogQLFunctionMeta("bitmapMin", 1, 1),
    "bitmapMax": HogQLFunctionMeta("bitmapMax", 1, 1),
    "bitmapTransform": HogQLFunctionMeta("bitmapTransform", 3, 3),
    "bitmapAnd": HogQLFunctionMeta("bitmapAnd", 2, 2),
    "bitmapOr": HogQLFunctionMeta("bitmapOr", 2, 2),
    "bitmapXor": HogQLFunctionMeta("bitmapXor", 2, 2),
    "bitmapAndnot": HogQLFunctionMeta("bitmapAndnot", 2, 2),
    "bitmapAndCardinality": HogQLFunctionMeta("bitmapAndCardinality", 2, 2),
    "bitmapOrCardinality": HogQLFunctionMeta("bitmapOrCardinality", 2, 2),
    "bitmapXorCardinality": HogQLFunctionMeta("bitmapXorCardinality", 2, 2),
    "bitmapAndnotCardinality": HogQLFunctionMeta("bitmapAndnotCardinality", 2, 2),
    # urls TODO
    "protocol": HogQLFunctionMeta("protocol", 1, 1),
    "domain": HogQLFunctionMeta("domain", 1, 1),
    "domainWithoutWWW": HogQLFunctionMeta("domainWithoutWWW", 1, 1),
    "topLevelDomain": HogQLFunctionMeta("topLevelDomain", 1, 1),
    "firstSignificantSubdomain": HogQLFunctionMeta("firstSignificantSubdomain", 1, 1),
    "cutToFirstSignificantSubdomain": HogQLFunctionMeta("cutToFirstSignificantSubdomain", 1, 1),
    "cutToFirstSignificantSubdomainWithWWW": HogQLFunctionMeta("cutToFirstSignificantSubdomainWithWWW", 1, 1),
    "port": HogQLFunctionMeta("port", 1, 2),
    "path": HogQLFunctionMeta("path", 1, 1),
    "pathFull": HogQLFunctionMeta("pathFull", 1, 1),
    "queryString": HogQLFunctionMeta("queryString", 1, 1),
    "fragment": HogQLFunctionMeta("fragment", 1, 1),
    "queryStringAndFragment": HogQLFunctionMeta("queryStringAndFragment", 1, 1),
    "extractURLParameter": HogQLFunctionMeta("extractURLParameter", 2, 2),
    "extractURLParameters": HogQLFunctionMeta("extractURLParameters", 1, 1),
    "extractURLParameterNames": HogQLFunctionMeta("extractURLParameterNames", 1, 1),
    "URLHierarchy": HogQLFunctionMeta("URLHierarchy", 1, 1),
    "URLPathHierarchy": HogQLFunctionMeta("URLPathHierarchy", 1, 1),
    "encodeURLComponent": HogQLFunctionMeta("encodeURLComponent", 1, 1),
    "decodeURLComponent": HogQLFunctionMeta("decodeURLComponent", 1, 1),
    "encodeURLFormComponent": HogQLFunctionMeta("encodeURLFormComponent", 1, 1),
    "decodeURLFormComponent": HogQLFunctionMeta("decodeURLFormComponent", 1, 1),
    "netloc": HogQLFunctionMeta("netloc", 1, 1),
    "cutWWW": HogQLFunctionMeta("cutWWW", 1, 1),
    "cutQueryString": HogQLFunctionMeta("cutQueryString", 1, 1),
    "cutFragment": HogQLFunctionMeta("cutFragment", 1, 1),
    "cutQueryStringAndFragment": HogQLFunctionMeta("cutQueryStringAndFragment", 1, 1),
    "cutURLParameter": HogQLFunctionMeta("cutURLParameter", 2, 2),
    # json
    "isValidJSON": HogQLFunctionMeta("isValidJSON", 1, 1),
    "JSONHas": HogQLFunctionMeta("JSONHas", 1, None),
    "JSONLength": HogQLFunctionMeta("JSONLength", 1, None),
    "JSONArrayLength": HogQLFunctionMeta("JSONArrayLength", 1, None),
    "JSONType": HogQLFunctionMeta("JSONType", 1, None),
    "JSONExtract": HogQLFunctionMeta("JSONExtract", 2, None),
    "JSONExtractUInt": HogQLFunctionMeta("JSONExtractUInt", 1, None),
    "JSONExtractInt": HogQLFunctionMeta("JSONExtractInt", 1, None),
    "JSONExtractFloat": HogQLFunctionMeta("JSONExtractFloat", 1, None),
    "JSONExtractBool": HogQLFunctionMeta("JSONExtractBool", 1, None),
    "JSONExtractString": HogQLFunctionMeta("JSONExtractString", 1, None),
    "JSONExtractKey": HogQLFunctionMeta("JSONExtractKey", 1, None),
    "JSONExtractKeys": HogQLFunctionMeta("JSONExtractKeys", 1, None),
    "JSONExtractRaw": HogQLFunctionMeta("JSONExtractRaw", 1, None),
    "JSONExtractArrayRaw": HogQLFunctionMeta("JSONExtractArrayRaw", 1, None),
    "JSONExtractKeysAndValues": HogQLFunctionMeta("JSONExtractKeysAndValues", 1, 3),
    "JSONExtractKeysAndValuesRaw": HogQLFunctionMeta("JSONExtractKeysAndValuesRaw", 1, None),
    "JSON_VALUE": HogQLFunctionMeta("JSON_VALUE", 2, None),
    # in
    "in": HogQLFunctionMeta("in", 2, 2),
    "notIn": HogQLFunctionMeta("notIn", 2, 2),
    # geo
    "greatCircleDistance": HogQLFunctionMeta("greatCircleDistance", 4, 4),
    "geoDistance": HogQLFunctionMeta("geoDistance", 4, 4),
    "greatCircleAngle": HogQLFunctionMeta("greatCircleAngle", 4, 4),
    "pointInEllipses": HogQLFunctionMeta("pointInEllipses", 6, None),
    "pointInPolygon": HogQLFunctionMeta("pointInPolygon", 2, None),
    "geohashEncode": HogQLFunctionMeta("geohashEncode", 2, 3),
    "geohashDecode": HogQLFunctionMeta("geohashDecode", 1, 1),
    "geohashesInBox": HogQLFunctionMeta("geohashesInBox", 5, 5),
    "h3IsValid": HogQLFunctionMeta(
        "h3IsValid",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetResolution": HogQLFunctionMeta(
        "h3GetResolution",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetBaseCell": HogQLFunctionMeta(
        "h3GetBaseCell",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3EdgeAngle": HogQLFunctionMeta(
        "h3EdgeAngle",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3EdgeLengthM": HogQLFunctionMeta(
        "h3EdgeLengthM",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3EdgeLengthKm": HogQLFunctionMeta(
        "h3EdgeLengthKm",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "geoToH3": HogQLFunctionMeta(
        "geoToH3",
        3,
        3,
        signatures=[
            ((FloatType(), FloatType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ToGeo": HogQLFunctionMeta(
        "h3ToGeo",
        1,
        1,
        signatures=[
            ((IntegerType(),), TupleType(item_types=[FloatType(), FloatType()])),
        ],
    ),
    "h3ToGeoBoundary": HogQLFunctionMeta(
        "h3ToGeoBoundary",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=TupleType(item_types=[FloatType(), FloatType()]))),
        ],
    ),
    "h3kRing": HogQLFunctionMeta(
        "h3kRing",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3HexAreaM2": HogQLFunctionMeta(
        "h3HexAreaM2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3HexAreaKm2": HogQLFunctionMeta(
        "h3HexAreaKm2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3IndexesAreNeighbors": HogQLFunctionMeta(
        "h3IndexesAreNeighbors",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ToChildren": HogQLFunctionMeta(
        "h3ToChildren",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3ToParent": HogQLFunctionMeta(
        "h3ToParent",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ToString": HogQLFunctionMeta(
        "h3ToString",
        1,
        1,
        signatures=[
            ((IntegerType(),), StringType()),
        ],
    ),
    "stringToH3": HogQLFunctionMeta(
        "stringToH3",
        1,
        1,
        signatures=[
            ((StringType(),), IntegerType()),
        ],
    ),
    "h3IsResClassIII": HogQLFunctionMeta(
        "h3IsResClassIII",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3IsPentagon": HogQLFunctionMeta(
        "h3IsPentagon",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetFaces": HogQLFunctionMeta(
        "h3GetFaces",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3CellAreaM2": HogQLFunctionMeta(
        "h3CellAreaM2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3CellAreaRads2": HogQLFunctionMeta(
        "h3CellAreaRads2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3ToCenterChild": HogQLFunctionMeta(
        "h3ToCenterChild",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ExactEdgeLengthM": HogQLFunctionMeta(
        "h3ExactEdgeLengthM",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3ExactEdgeLengthKm": HogQLFunctionMeta(
        "h3ExactEdgeLengthKm",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3ExactEdgeLengthRads": HogQLFunctionMeta(
        "h3ExactEdgeLengthRads",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3NumHexagons": HogQLFunctionMeta(
        "h3NumHexagons",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3PointDistM": HogQLFunctionMeta(
        "h3PointDistM",
        4,
        4,
        signatures=[
            ((FloatType(), FloatType(), FloatType(), FloatType()), FloatType()),
        ],
    ),
    "h3PointDistKm": HogQLFunctionMeta(
        "h3PointDistKm",
        4,
        4,
        signatures=[
            ((FloatType(), FloatType(), FloatType(), FloatType()), FloatType()),
        ],
    ),
    "h3PointDistRads": HogQLFunctionMeta(
        "h3PointDistRads",
        4,
        4,
        signatures=[
            ((FloatType(), FloatType(), FloatType(), FloatType()), FloatType()),
        ],
    ),
    "h3GetRes0Indexes": HogQLFunctionMeta(
        "h3GetRes0Indexes",
        0,
        0,
        signatures=[
            ((), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3GetPentagonIndexes": HogQLFunctionMeta(
        "h3GetPentagonIndexes",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3Line": HogQLFunctionMeta(
        "h3Line",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3Distance": HogQLFunctionMeta(
        "h3Distance",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3HexRing": HogQLFunctionMeta(
        "h3HexRing",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3GetUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetUnidirectionalEdge",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3UnidirectionalEdgeIsValid": HogQLFunctionMeta(
        "h3UnidirectionalEdgeIsValid",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetOriginIndexFromUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetOriginIndexFromUnidirectionalEdge",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetDestinationIndexFromUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetDestinationIndexFromUnidirectionalEdge",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetIndexesFromUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetIndexesFromUnidirectionalEdge",
        1,
        1,
        signatures=[
            ((IntegerType(),), TupleType(item_types=[IntegerType(), IntegerType()])),
        ],
    ),
    "h3GetUnidirectionalEdgesFromHexagon": HogQLFunctionMeta(
        "h3GetUnidirectionalEdgesFromHexagon",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3GetUnidirectionalEdgeBoundary": HogQLFunctionMeta(
        "h3GetUnidirectionalEdgeBoundary",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=TupleType(item_types=[FloatType(), FloatType()]))),
        ],
    ),
    # nullable
    "isnull": HogQLFunctionMeta("isNull", 1, 1, case_sensitive=False),
    "isNotNull": HogQLFunctionMeta("isNotNull", 1, 1),
    "coalesce": HogQLFunctionMeta("coalesce", 1, None, case_sensitive=False),
    "ifnull": HogQLFunctionMeta("ifNull", 2, 2, case_sensitive=False),
    "nullif": HogQLFunctionMeta("nullIf", 2, 2, case_sensitive=False),
    "assumeNotNull": HogQLFunctionMeta(
        "assumeNotNull",
        1,
        1,
        signatures=[
            ((DateTimeType(),), DateTimeType()),
        ],
    ),
    "toNullable": HogQLFunctionMeta("toNullable", 1, 1),
    # tuples
    "tuple": HogQLFunctionMeta("tuple", 0, None),
    "tupleElement": HogQLFunctionMeta("tupleElement", 2, 3),
    "untuple": HogQLFunctionMeta("untuple", 1, 1),
    "tupleHammingDistance": HogQLFunctionMeta("tupleHammingDistance", 2, 2),
    "tupleToNameValuePairs": HogQLFunctionMeta("tupleToNameValuePairs", 1, 1),
    "tuplePlus": HogQLFunctionMeta("tuplePlus", 2, 2),
    "tupleMinus": HogQLFunctionMeta("tupleMinus", 2, 2),
    "tupleMultiply": HogQLFunctionMeta("tupleMultiply", 2, 2),
    "tupleDivide": HogQLFunctionMeta("tupleDivide", 2, 2),
    "tupleNegate": HogQLFunctionMeta("tupleNegate", 1, 1),
    "tupleMultiplyByNumber": HogQLFunctionMeta("tupleMultiplyByNumber", 2, 2),
    "tupleDivideByNumber": HogQLFunctionMeta("tupleDivideByNumber", 2, 2),
    "dotProduct": HogQLFunctionMeta("dotProduct", 2, 2),
    # other
    "isFinite": HogQLFunctionMeta("isFinite", 1, 1),
    "isInfinite": HogQLFunctionMeta("isInfinite", 1, 1),
    "ifNotFinite": HogQLFunctionMeta("ifNotFinite", 1, 1),
    "isNaN": HogQLFunctionMeta("isNaN", 1, 1),
    "bar": HogQLFunctionMeta("bar", 4, 4),
    "transform": HogQLFunctionMeta("transform", 3, 4),
    "formatReadableDecimalSize": HogQLFunctionMeta("formatReadableDecimalSize", 1, 1),
    "formatReadableSize": HogQLFunctionMeta("formatReadableSize", 1, 1),
    "formatReadableQuantity": HogQLFunctionMeta("formatReadableQuantity", 1, 1),
    "formatReadableTimeDelta": HogQLFunctionMeta("formatReadableTimeDelta", 1, 2),
    "least": HogQLFunctionMeta("least", 2, 2, case_sensitive=False),
    "greatest": HogQLFunctionMeta("greatest", 2, 2, case_sensitive=False),
    # time window
    "tumble": HogQLFunctionMeta("tumble", 2, 2),
    "hop": HogQLFunctionMeta("hop", 3, 3),
    "tumbleStart": HogQLFunctionMeta("tumbleStart", 1, 3),
    "tumbleEnd": HogQLFunctionMeta("tumbleEnd", 1, 3),
    "hopStart": HogQLFunctionMeta("hopStart", 1, 3),
    "hopEnd": HogQLFunctionMeta("hopEnd", 1, 3),
    # distance window
    "L1Norm": HogQLFunctionMeta("L1Norm", 1, 1),
    "L2Norm": HogQLFunctionMeta("L2Norm", 1, 1),
    "LinfNorm": HogQLFunctionMeta("LinfNorm", 1, 1),
    "LpNorm": HogQLFunctionMeta("LpNorm", 2, 2),
    "L1Distance": HogQLFunctionMeta("L1Distance", 2, 2),
    "L2Distance": HogQLFunctionMeta("L2Distance", 2, 2),
    "LinfDistance": HogQLFunctionMeta("LinfDistance", 2, 2),
    "LpDistance": HogQLFunctionMeta("LpDistance", 3, 3),
    "L1Normalize": HogQLFunctionMeta("L1Normalize", 1, 1),
    "L2Normalize": HogQLFunctionMeta("L2Normalize", 1, 1),
    "LinfNormalize": HogQLFunctionMeta("LinfNormalize", 1, 1),
    "LpNormalize": HogQLFunctionMeta("LpNormalize", 2, 2),
    "cosineDistance": HogQLFunctionMeta("cosineDistance", 2, 2),
    # window functions
    "rank": HogQLFunctionMeta("rank"),
    "dense_rank": HogQLFunctionMeta("dense_rank"),
    "row_number": HogQLFunctionMeta("row_number"),
    "first_value": HogQLFunctionMeta("first_value", 1, 1),
    "last_value": HogQLFunctionMeta("last_value", 1, 1),
    "nth_value": HogQLFunctionMeta("nth_value", 2, 2),
    "lagInFrame": HogQLFunctionMeta("lagInFrame", 1, 1),
    "leadInFrame": HogQLFunctionMeta("leadInFrame", 1, 1),
    # table functions
    "generateSeries": HogQLFunctionMeta("generate_series", 3, 3),
    # PostgreSQL-style date/time functions
    "date_part": HogQLFunctionMeta(
        "if({0} = 'year', toYear({1}), if({0} = 'month', toMonth({1}), if({0} = 'day', toDayOfMonth({1}), if({0} = 'hour', toHour({1}), if({0} = 'minute', toMinute({1}), if({0} = 'second', toSecond({1}), if({0} = 'dow', toDayOfWeek({1}), if({0} = 'doy', toDayOfYear({1}), if({0} = 'quarter', toQuarter({1}), null)))))))))",  # Maps to same implementation as extract
        2,
        2,
        signatures=[
            ((StringType(), DateTimeType()), IntegerType()),
            ((StringType(), DateType()), IntegerType()),
        ],
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    **{
        name: HogQLFunctionMeta(
            "dateTrunc",
            2,
            3,  # Allow optional timezone parameter
            signatures=[
                ((StringType(), DateTimeType()), DateTimeType()),
                ((StringType(), DateTimeType(), StringType()), DateTimeType()),
            ],
        )
        for name in ["date_trunc", "dateTrunc"]
    },
    "to_timestamp": HogQLFunctionMeta(
        "toDateTime(fromUnixTimestamp({}))",
        1,
        2,
        tz_aware=True,
        signatures=[
            ((IntegerType(),), DateTimeType()),
            ((FloatType(),), DateTimeType()),
        ],
        using_placeholder_arguments=True,
    ),
    "to_char": HogQLFunctionMeta(
        "formatDateTime",
        2,
        3,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), StringType()), StringType()),
            ((DateTimeType(), StringType(), StringType()), StringType()),
        ],
    ),
    "make_timestamp": HogQLFunctionMeta(
        "makeDateTime",
        6,
        7,
        tz_aware=True,
        signatures=[
            ((IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), FloatType()), DateTimeType()),
            (
                (IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), FloatType(), StringType()),
                DateTimeType(),
            ),
        ],
    ),
    "make_date": HogQLFunctionMeta(
        "makeDate",
        3,
        3,
        signatures=[
            ((IntegerType(), IntegerType(), IntegerType()), DateType()),
        ],
    ),
    "now": HogQLFunctionMeta(
        "now64",
        0,
        1,
        tz_aware=True,
        case_sensitive=False,
        signatures=[
            ((), DateTimeType()),
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "current_timestamp": HogQLFunctionMeta(
        "now64",
        0,
        0,
        tz_aware=True,
        signatures=[
            ((), DateTimeType()),
        ],
    ),
    **{
        name: HogQLFunctionMeta(
            "today",
            0,
            0,
            signatures=[
                ((), DateType()),
            ],
        )
        for name in ["today", "current_date"]
    },
    #  This doesn't work yet but will in a new version of Clickhouse: https://github.com/ClickHouse/ClickHouse/pull/56738
    # "date_bin": HogQLFunctionMeta(
    #     "toSTartOfInterval({1}, {0}, {2})",
    #     3,
    #     3,
    #     tz_aware=True,
    #     signatures=[
    #         ((IntervalType(), DateTimeType(), DateTimeType()), DateTimeType()),
    #     ],
    # ),
    "date_add": HogQLFunctionMeta(
        "date_add",
        2,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
        ],
    ),
    "date_subtract": HogQLFunctionMeta(
        "date_sub",
        2,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
        ],
    ),
    **{
        name: HogQLFunctionMeta(
            "dateDiff",
            3,
            3,
            signatures=[
                ((StringType(), DateTimeType(), DateTimeType()), IntegerType()),
            ],
        )
        for name in ["date_diff", "dateDiff"]
    },
    "make_interval": HogQLFunctionMeta(
        "toIntervalYear({}) + toIntervalMonth({}) + toIntervalDay({}) + toIntervalHour({}) + toIntervalMinute({}) + toIntervalSecond({})",  # Changed from makeInterval to addInterval
        6,
        6,
        signatures=[
            (
                (IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType()),
                DateTimeType(),
            ),
        ],
        using_placeholder_arguments=True,
    ),
    # Clickhouse doesn't have a TIME type, so this would be the alternative
    # "make_time": HogQLFunctionMeta(
    #     "toTime(makeDateTime(1970, 1, 1, {}, {}, {}))",
    #     3,
    #     3,
    #     signatures=[((IntegerType(), IntegerType(), FloatType()), DateTimeType())],
    # ),
    "make_timestamptz": HogQLFunctionMeta(
        "toTimeZone(makeDateTime({}, {}, {}, {}, {}, {}), {})",
        7,
        7,
        signatures=[
            (
                (IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), FloatType(), StringType()),
                DateTimeType(),
            ),
        ],
        tz_aware=True,
        using_placeholder_arguments=True,
    ),
    "timezone": HogQLFunctionMeta(
        "toTimeZone({1}, {0})",
        2,
        2,
        signatures=[((StringType(), DateTimeType()), DateTimeType())],
        tz_aware=True,
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    "toTimeZone": HogQLFunctionMeta(
        "toTimeZone",
        1,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), StringType()), DateTimeType()),
        ],
    ),
    # Window functions in PostgreSQL style
    "lag": HogQLFunctionMeta(
        "lagInFrame",
        1,
        3,
        signatures=[
            ((UnknownType(),), UnknownType()),
            ((UnknownType(), IntegerType()), UnknownType()),
            ((UnknownType(), IntegerType(), UnknownType()), UnknownType()),
        ],
    ),
    "lead": HogQLFunctionMeta(
        "leadInFrame",
        1,
        3,
        signatures=[
            ((UnknownType(),), UnknownType()),
            ((UnknownType(), IntegerType()), UnknownType()),
            ((UnknownType(), IntegerType(), UnknownType()), UnknownType()),
        ],
    ),
    # String functions
    "repeat": HogQLFunctionMeta(
        "repeat",
        2,
        2,
        signatures=[((StringType(), IntegerType()), StringType())],
    ),
    "initcap": HogQLFunctionMeta(
        "initcap",
        1,
        1,
        signatures=[((StringType(),), StringType())],
    ),
    "lpad": HogQLFunctionMeta(
        "lpad",
        3,
        3,
        signatures=[((StringType(), IntegerType(), StringType()), StringType())],
    ),
    "rpad": HogQLFunctionMeta(
        "rpad",
        3,
        3,
        signatures=[((StringType(), IntegerType(), StringType()), StringType())],
    ),
    **{
        name: HogQLFunctionMeta(
            "trimLeft",
            1,
            2,
            signatures=[
                ((StringType(),), StringType()),
                ((StringType(), StringType()), StringType()),
            ],
        )
        for name in ["ltrim", "trimLeft"]
    },
    **{
        name: HogQLFunctionMeta(
            "trimRight",
            1,
            2,
            signatures=[
                ((StringType(),), StringType()),
                ((StringType(), StringType()), StringType()),
            ],
        )
        for name in ["rtrim", "trimRight"]
    },
    **{
        name: HogQLFunctionMeta(
            "trim",
            1,
            2,
            signatures=[
                ((StringType(),), StringType()),
                ((StringType(), StringType()), StringType()),
            ],
            case_sensitive=False,
        )
        for name in ["btrim", "trim"]
    },
    "split_part": HogQLFunctionMeta(
        # We need to repeat each argument in the format string since we use each one multiple times
        "if(empty(splitByString({1}, {0})), '', if(length(splitByString({1}, {0})) >= {2}, arrayElement(splitByString({1}, {0}), {2}), ''))",
        3,
        3,
        signatures=[((StringType(), StringType(), IntegerType()), StringType())],
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    # survey functions
    "getSurveyResponse": HogQLFunctionMeta(
        "getSurveyResponse", 1, 3, signatures=[((IntegerType(), StringType(), BooleanType()), StringType())]
    ),
    "uniqueSurveySubmissionsFilter": HogQLFunctionMeta(
        "uniqueSurveySubmissionsFilter", 1, 1, signatures=[((StringType(),), StringType())]
    ),
}

# Permitted HogQL aggregations
HOGQL_AGGREGATIONS: dict[str, HogQLFunctionMeta] = {
    # Standard aggregate functions
    "count": HogQLFunctionMeta("count", 0, 1, aggregate=True, case_sensitive=False),
    "countIf": HogQLFunctionMeta("countIf", 1, 2, aggregate=True),
    "countState": HogQLFunctionMeta("countState", 0, 1, aggregate=True),
    "countMerge": HogQLFunctionMeta("countMerge", 1, 1, aggregate=True),
    "countStateIf": HogQLFunctionMeta("countStateIf", 1, 2, aggregate=True),
    "countDistinctIf": HogQLFunctionMeta("countDistinctIf", 1, 2, aggregate=True),
    "countMapIf": HogQLFunctionMeta("countMapIf", 2, 3, aggregate=True),
    "min": HogQLFunctionMeta("min", 1, 1, aggregate=True, case_sensitive=False),
    "minIf": HogQLFunctionMeta("minIf", 2, 2, aggregate=True),
    "max": HogQLFunctionMeta("max", 1, 1, aggregate=True, case_sensitive=False),
    "maxIf": HogQLFunctionMeta("maxIf", 2, 2, aggregate=True),
    "sum": HogQLFunctionMeta("sum", 1, 1, aggregate=True, case_sensitive=False),
    "sumForEach": HogQLFunctionMeta("sumForEach", 1, 1, aggregate=True),
    "sumIf": HogQLFunctionMeta("sumIf", 2, 2, aggregate=True),
    "avg": HogQLFunctionMeta("avg", 1, 1, aggregate=True, case_sensitive=False),
    "avgIf": HogQLFunctionMeta("avgIf", 2, 2, aggregate=True),
    "avgMap": HogQLFunctionMeta("avgMap", 1, 1, aggregate=True),
    "avgMapIf": HogQLFunctionMeta("avgMapIf", 2, 3, aggregate=True),
    "avgMapState": HogQLFunctionMeta("avgMapState", 2, 3, aggregate=True),
    "avgMapMerge": HogQLFunctionMeta("avgMapMerge", 1, 1, aggregate=True),
    "avgMapMergeIf": HogQLFunctionMeta("avgMapMergeIf", 2, 2, aggregate=True),
    "any": HogQLFunctionMeta("any", 1, 1, aggregate=True),
    "anyIf": HogQLFunctionMeta("anyIf", 2, 2, aggregate=True),
    "stddevPop": HogQLFunctionMeta("stddevPop", 1, 1, aggregate=True),
    "stddevPopIf": HogQLFunctionMeta("stddevPopIf", 2, 2, aggregate=True),
    "stddevSamp": HogQLFunctionMeta("stddevSamp", 1, 1, aggregate=True),
    "stddevSampIf": HogQLFunctionMeta("stddevSampIf", 2, 2, aggregate=True),
    "varPop": HogQLFunctionMeta("varPop", 1, 1, aggregate=True),
    "varPopIf": HogQLFunctionMeta("varPopIf", 2, 2, aggregate=True),
    "varSamp": HogQLFunctionMeta("varSamp", 1, 1, aggregate=True),
    "varSampIf": HogQLFunctionMeta("varSampIf", 2, 2, aggregate=True),
    "covarPop": HogQLFunctionMeta("covarPop", 2, 2, aggregate=True),
    "covarPopIf": HogQLFunctionMeta("covarPopIf", 3, 3, aggregate=True),
    "covarSamp": HogQLFunctionMeta("covarSamp", 2, 2, aggregate=True),
    "covarSampIf": HogQLFunctionMeta("covarSampIf", 3, 3, aggregate=True),
    "corr": HogQLFunctionMeta("corr", 2, 2, aggregate=True),
    # PostgreSQL-style aggregate functions
    **{
        name: HogQLFunctionMeta(
            "groupArray",
            1,
            1,
            aggregate=True,
            signatures=[((UnknownType(),), ArrayType(item_type=UnknownType()))],
        )
        for name in ["array_agg", "groupArray"]
    },
    "json_agg": HogQLFunctionMeta(
        "toJSONString(groupArray({}))",
        1,
        1,
        aggregate=True,
        signatures=[((UnknownType(),), StringType())],
        using_placeholder_arguments=True,
    ),
    "string_agg": HogQLFunctionMeta(
        "arrayStringConcat(groupArray({}), {})",
        2,
        2,
        aggregate=True,
        signatures=[((StringType(), StringType()), StringType())],
        using_placeholder_arguments=True,
    ),
    "every": HogQLFunctionMeta(
        "toBool(min({}))",
        1,
        1,
        aggregate=True,
        signatures=[((UnknownType(),), BooleanType())],
        using_placeholder_arguments=True,
    ),
    # ClickHouse-specific aggregate functions
    "anyHeavy": HogQLFunctionMeta("anyHeavy", 1, 1, aggregate=True),
    "anyHeavyIf": HogQLFunctionMeta("anyHeavyIf", 2, 2, aggregate=True),
    "anyLast": HogQLFunctionMeta("anyLast", 1, 1, aggregate=True),
    "anyLastIf": HogQLFunctionMeta("anyLastIf", 2, 2, aggregate=True),
    "argMin": HogQLFunctionMeta("argMin", 2, 2, aggregate=True),
    "argMinIf": HogQLFunctionMeta("argMinIf", 3, 3, aggregate=True),
    "argMax": HogQLFunctionMeta("argMax", 2, 2, aggregate=True),
    "argMaxIf": HogQLFunctionMeta("argMaxIf", 3, 3, aggregate=True),
    "argMinMerge": HogQLFunctionMeta("argMinMerge", 1, 1, aggregate=True),
    "argMaxMerge": HogQLFunctionMeta("argMaxMerge", 1, 1, aggregate=True),
    "avgState": HogQLFunctionMeta("avgState", 1, 1, aggregate=True),
    "avgStateIf": HogQLFunctionMeta("avgStateIf", 2, 2, aggregate=True),
    "avgMerge": HogQLFunctionMeta("avgMerge", 1, 1, aggregate=True),
    "avgMergeIf": HogQLFunctionMeta("avgMergeIf", 2, 2, aggregate=True),
    "avgWeighted": HogQLFunctionMeta("avgWeighted", 2, 2, aggregate=True),
    "avgWeightedIf": HogQLFunctionMeta("avgWeightedIf", 3, 3, aggregate=True),
    "avgArray": HogQLFunctionMeta("avgArrayOrNull", 1, 1, aggregate=True),
    "topK": HogQLFunctionMeta("topK", 1, 1, min_params=1, max_params=1, aggregate=True),
    # "topKIf": HogQLFunctionMeta("topKIf", 2, 2, aggregate=True),
    # "topKWeighted": HogQLFunctionMeta("topKWeighted", 1, 1, aggregate=True),
    # "topKWeightedIf": HogQLFunctionMeta("topKWeightedIf", 2, 2, aggregate=True),
    "groupArrayIf": HogQLFunctionMeta("groupArrayIf", 2, 2, aggregate=True),
    # "groupArrayLast": HogQLFunctionMeta("groupArrayLast", 1, 1, aggregate=True),
    # "groupArrayLastIf": HogQLFunctionMeta("groupArrayLastIf", 2, 2, aggregate=True),
    "groupUniqArray": HogQLFunctionMeta("groupUniqArray", 1, 1, aggregate=True),
    "groupUniqArrayIf": HogQLFunctionMeta("groupUniqArrayIf", 2, 2, aggregate=True),
    "groupArrayInsertAt": HogQLFunctionMeta("groupArrayInsertAt", 2, 2, aggregate=True),
    "groupArrayInsertAtIf": HogQLFunctionMeta("groupArrayInsertAtIf", 3, 3, aggregate=True),
    "groupArrayMovingAvg": HogQLFunctionMeta("groupArrayMovingAvg", 1, 1, aggregate=True),
    "groupArrayMovingAvgIf": HogQLFunctionMeta("groupArrayMovingAvgIf", 2, 2, aggregate=True),
    "groupArrayMovingSum": HogQLFunctionMeta("groupArrayMovingSum", 1, 1, aggregate=True),
    "groupArrayMovingSumIf": HogQLFunctionMeta("groupArrayMovingSumIf", 2, 2, aggregate=True),
    "groupBitAnd": HogQLFunctionMeta("groupBitAnd", 1, 1, aggregate=True),
    "groupBitAndIf": HogQLFunctionMeta("groupBitAndIf", 2, 2, aggregate=True),
    "groupBitOr": HogQLFunctionMeta("groupBitOr", 1, 1, aggregate=True),
    "groupBitOrIf": HogQLFunctionMeta("groupBitOrIf", 2, 2, aggregate=True),
    "groupBitXor": HogQLFunctionMeta("groupBitXor", 1, 1, aggregate=True),
    "groupBitXorIf": HogQLFunctionMeta("groupBitXorIf", 2, 2, aggregate=True),
    "groupBitmap": HogQLFunctionMeta("groupBitmap", 1, 1, aggregate=True),
    "groupBitmapIf": HogQLFunctionMeta("groupBitmapIf", 2, 2, aggregate=True),
    "groupBitmapAnd": HogQLFunctionMeta("groupBitmapAnd", 1, 1, aggregate=True),
    "groupBitmapAndIf": HogQLFunctionMeta("groupBitmapAndIf", 2, 2, aggregate=True),
    "groupBitmapOr": HogQLFunctionMeta("groupBitmapOr", 1, 1, aggregate=True),
    "groupBitmapOrIf": HogQLFunctionMeta("groupBitmapOrIf", 2, 2, aggregate=True),
    "groupBitmapXor": HogQLFunctionMeta("groupBitmapXor", 1, 1, aggregate=True),
    "groupBitmapXorIf": HogQLFunctionMeta("groupBitmapXorIf", 2, 2, aggregate=True),
    "sumWithOverflow": HogQLFunctionMeta("sumWithOverflow", 1, 1, aggregate=True),
    "sumWithOverflowIf": HogQLFunctionMeta("sumWithOverflowIf", 2, 2, aggregate=True),
    "deltaSum": HogQLFunctionMeta("deltaSum", 1, 1, aggregate=True),
    "deltaSumIf": HogQLFunctionMeta("deltaSumIf", 2, 2, aggregate=True),
    "deltaSumTimestamp": HogQLFunctionMeta("deltaSumTimestamp", 2, 2, aggregate=True),
    "deltaSumTimestampIf": HogQLFunctionMeta("deltaSumTimestampIf", 3, 3, aggregate=True),
    "sumMap": HogQLFunctionMeta("sumMap", 1, 2, aggregate=True),
    "sumMapIf": HogQLFunctionMeta("sumMapIf", 2, 3, aggregate=True),
    "sumMapMerge": HogQLFunctionMeta("sumMapMerge", 1, 1, aggregate=True),
    "sumMapMergeIf": HogQLFunctionMeta("sumMapMergeIf", 2, 2, aggregate=True),
    "minMap": HogQLFunctionMeta("minMap", 1, 2, aggregate=True),
    "minMapIf": HogQLFunctionMeta("minMapIf", 2, 3, aggregate=True),
    "maxMap": HogQLFunctionMeta("maxMap", 1, 2, aggregate=True),
    "maxMapIf": HogQLFunctionMeta("maxMapIf", 2, 3, aggregate=True),
    "sumMerge": HogQLFunctionMeta("sumMerge", 1, 1, aggregate=True),
    "sumMergeIf": HogQLFunctionMeta("sumMergeIf", 2, 2, aggregate=True),
    "sumState": HogQLFunctionMeta("sumState", 1, 1, aggregate=True),
    "sumStateIf": HogQLFunctionMeta("sumStateIf", 2, 2, aggregate=True),
    "medianArray": HogQLFunctionMeta("medianArrayOrNull", 1, 1, aggregate=True),
    "skewSamp": HogQLFunctionMeta("skewSamp", 1, 1, aggregate=True),
    "skewSampIf": HogQLFunctionMeta("skewSampIf", 2, 2, aggregate=True),
    "skewPop": HogQLFunctionMeta("skewPop", 1, 1, aggregate=True),
    "skewPopIf": HogQLFunctionMeta("skewPopIf", 2, 2, aggregate=True),
    "kurtSamp": HogQLFunctionMeta("kurtSamp", 1, 1, aggregate=True),
    "kurtSampIf": HogQLFunctionMeta("kurtSampIf", 2, 2, aggregate=True),
    "kurtPop": HogQLFunctionMeta("kurtPop", 1, 1, aggregate=True),
    "kurtPopIf": HogQLFunctionMeta("kurtPopIf", 2, 2, aggregate=True),
    "uniq": HogQLFunctionMeta("uniq", 1, None, aggregate=True),
    "uniqIf": HogQLFunctionMeta("uniqIf", 2, None, aggregate=True),
    "uniqExact": HogQLFunctionMeta("uniqExact", 1, None, aggregate=True),
    "uniqExactIf": HogQLFunctionMeta("uniqExactIf", 2, None, aggregate=True),
    # "uniqCombined": HogQLFunctionMeta("uniqCombined", 1, 1, aggregate=True),
    # "uniqCombinedIf": HogQLFunctionMeta("uniqCombinedIf", 2, 2, aggregate=True),
    # "uniqCombined64": HogQLFunctionMeta("uniqCombined64", 1, 1, aggregate=True),
    # "uniqCombined64If": HogQLFunctionMeta("uniqCombined64If", 2, 2, aggregate=True),
    "uniqHLL12": HogQLFunctionMeta("uniqHLL12", 1, None, aggregate=True),
    "uniqHLL12If": HogQLFunctionMeta("uniqHLL12If", 2, None, aggregate=True),
    "uniqTheta": HogQLFunctionMeta("uniqTheta", 1, None, aggregate=True),
    "uniqThetaIf": HogQLFunctionMeta("uniqThetaIf", 2, None, aggregate=True),
    "uniqMerge": HogQLFunctionMeta("uniqMerge", 1, 1, aggregate=True),
    "uniqMergeIf": HogQLFunctionMeta("uniqMergeIf", 2, 2, aggregate=True),
    "uniqMap": HogQLFunctionMeta("uniqMap", 1, 1, aggregate=True),
    "uniqMapMerge": HogQLFunctionMeta("uniqMapMerge", 1, 1, aggregate=True),
    "uniqMapMergeIf": HogQLFunctionMeta("uniqMapMergeIf", 2, 2, aggregate=True),
    "uniqState": HogQLFunctionMeta("uniqState", 1, 1, aggregate=True),
    "uniqStateIf": HogQLFunctionMeta("uniqStateIf", 2, 2, aggregate=True),
    "uniqUpToMerge": HogQLFunctionMeta("uniqUpToMerge", 1, 1, 1, 1, aggregate=True),
    "median": HogQLFunctionMeta("median", 1, 1, aggregate=True),
    "medianIf": HogQLFunctionMeta("medianIf", 2, 2, aggregate=True),
    "medianExact": HogQLFunctionMeta("medianExact", 1, 1, aggregate=True),
    "medianExactIf": HogQLFunctionMeta("medianExactIf", 2, 2, aggregate=True),
    "medianExactLow": HogQLFunctionMeta("medianExactLow", 1, 1, aggregate=True),
    "medianExactLowIf": HogQLFunctionMeta("medianExactLowIf", 2, 2, aggregate=True),
    "medianExactHigh": HogQLFunctionMeta("medianExactHigh", 1, 1, aggregate=True),
    "medianExactHighIf": HogQLFunctionMeta("medianExactHighIf", 2, 2, aggregate=True),
    "medianExactWeighted": HogQLFunctionMeta("medianExactWeighted", 1, 1, aggregate=True),
    "medianExactWeightedIf": HogQLFunctionMeta("medianExactWeightedIf", 2, 2, aggregate=True),
    "medianTiming": HogQLFunctionMeta("medianTiming", 1, 1, aggregate=True),
    "medianTimingIf": HogQLFunctionMeta("medianTimingIf", 2, 2, aggregate=True),
    "medianTimingWeighted": HogQLFunctionMeta("medianTimingWeighted", 1, 1, aggregate=True),
    "medianTimingWeightedIf": HogQLFunctionMeta("medianTimingWeightedIf", 2, 2, aggregate=True),
    "medianDeterministic": HogQLFunctionMeta("medianDeterministic", 1, 1, aggregate=True),
    "medianDeterministicIf": HogQLFunctionMeta("medianDeterministicIf", 2, 2, aggregate=True),
    "medianTDigest": HogQLFunctionMeta("medianTDigest", 1, 1, aggregate=True),
    "medianTDigestIf": HogQLFunctionMeta("medianTDigestIf", 2, 2, aggregate=True),
    "medianTDigestWeighted": HogQLFunctionMeta("medianTDigestWeighted", 1, 1, aggregate=True),
    "medianTDigestWeightedIf": HogQLFunctionMeta("medianTDigestWeightedIf", 2, 2, aggregate=True),
    "medianBFloat16": HogQLFunctionMeta("medianBFloat16", 1, 1, aggregate=True),
    "medianBFloat16If": HogQLFunctionMeta("medianBFloat16If", 2, 2, aggregate=True),
    "quantile": HogQLFunctionMeta("quantile", 1, 1, min_params=1, max_params=1, aggregate=True),
    "quantileIf": HogQLFunctionMeta("quantileIf", 2, 2, min_params=1, max_params=1, aggregate=True),
    "quantiles": HogQLFunctionMeta("quantiles", 1, None, aggregate=True),
    "quantilesIf": HogQLFunctionMeta("quantilesIf", 2, 2, min_params=1, max_params=1, aggregate=True),
    # "quantileExact": HogQLFunctionMeta("quantileExact", 1, 1, aggregate=True),
    # "quantileExactIf": HogQLFunctionMeta("quantileExactIf", 2, 2, aggregate=True),
    # "quantileExactLow": HogQLFunctionMeta("quantileExactLow", 1, 1, aggregate=True),
    # "quantileExactLowIf": HogQLFunctionMeta("quantileExactLowIf", 2, 2, aggregate=True),
    # "quantileExactHigh": HogQLFunctionMeta("quantileExactHigh", 1, 1, aggregate=True),
    # "quantileExactHighIf": HogQLFunctionMeta("quantileExactHighIf", 2, 2, aggregate=True),
    # "quantileExactWeighted": HogQLFunctionMeta("quantileExactWeighted", 1, 1, aggregate=True),
    # "quantileExactWeightedIf": HogQLFunctionMeta("quantileExactWeightedIf", 2, 2, aggregate=True),
    # "quantileTiming": HogQLFunctionMeta("quantileTiming", 1, 1, aggregate=True),
    # "quantileTimingIf": HogQLFunctionMeta("quantileTimingIf", 2, 2, aggregate=True),
    # "quantileTimingWeighted": HogQLFunctionMeta("quantileTimingWeighted", 1, 1, aggregate=True),
    # "quantileTimingWeightedIf": HogQLFunctionMeta("quantileTimingWeightedIf", 2, 2, aggregate=True),
    # "quantileDeterministic": HogQLFunctionMeta("quantileDeterministic", 1, 1, aggregate=True),
    # "quantileDeterministicIf": HogQLFunctionMeta("quantileDeterministicIf", 2, 2, aggregate=True),
    # "quantileTDigest": HogQLFunctionMeta("quantileTDigest", 1, 1, aggregate=True),
    # "quantileTDigestIf": HogQLFunctionMeta("quantileTDigestIf", 2, 2, aggregate=True),
    # "quantileTDigestWeighted": HogQLFunctionMeta("quantileTDigestWeighted", 1, 1, aggregate=True),
    # "quantileTDigestWeightedIf": HogQLFunctionMeta("quantileTDigestWeightedIf", 2, 2, aggregate=True),
    # "quantileBFloat16": HogQLFunctionMeta("quantileBFloat16", 1, 1, aggregate=True),
    # "quantileBFloat16If": HogQLFunctionMeta("quantileBFloat16If", 2, 2, aggregate=True),
    # "quantileBFloat16Weighted": HogQLFunctionMeta("quantileBFloat16Weighted", 1, 1, aggregate=True),
    # "quantileBFloat16WeightedIf": HogQLFunctionMeta("quantileBFloat16WeightedIf", 2, 2, aggregate=True),
    "simpleLinearRegression": HogQLFunctionMeta("simpleLinearRegression", 2, 2, aggregate=True),
    "simpleLinearRegressionIf": HogQLFunctionMeta("simpleLinearRegressionIf", 3, 3, aggregate=True),
    # "stochasticLinearRegression": HogQLFunctionMeta("stochasticLinearRegression", 1, 1, aggregate=True),
    # "stochasticLinearRegressionIf": HogQLFunctionMeta("stochasticLinearRegressionIf", 2, 2, aggregate=True),
    # "stochasticLogisticRegression": HogQLFunctionMeta("stochasticLogisticRegression", 1, 1, aggregate=True),
    # "stochasticLogisticRegressionIf": HogQLFunctionMeta("stochasticLogisticRegressionIf", 2, 2, aggregate=True),
    # "categoricalInformationValue": HogQLFunctionMeta("categoricalInformationValue", 1, 1, aggregate=True),
    # "categoricalInformationValueIf": HogQLFunctionMeta("categoricalInformationValueIf", 2, 2, aggregate=True),
    "contingency": HogQLFunctionMeta("contingency", 2, 2, aggregate=True),
    "contingencyIf": HogQLFunctionMeta("contingencyIf", 3, 3, aggregate=True),
    "cramersV": HogQLFunctionMeta("cramersV", 2, 2, aggregate=True),
    "cramersVIf": HogQLFunctionMeta("cramersVIf", 3, 3, aggregate=True),
    "cramersVBiasCorrected": HogQLFunctionMeta("cramersVBiasCorrected", 2, 2, aggregate=True),
    "cramersVBiasCorrectedIf": HogQLFunctionMeta("cramersVBiasCorrectedIf", 3, 3, aggregate=True),
    "theilsU": HogQLFunctionMeta("theilsU", 2, 2, aggregate=True),
    "theilsUIf": HogQLFunctionMeta("theilsUIf", 3, 3, aggregate=True),
    "maxIntersections": HogQLFunctionMeta("maxIntersections", 2, 2, aggregate=True),
    "maxIntersectionsIf": HogQLFunctionMeta("maxIntersectionsIf", 3, 3, aggregate=True),
    "maxIntersectionsPosition": HogQLFunctionMeta("maxIntersectionsPosition", 2, 2, aggregate=True),
    "maxIntersectionsPositionIf": HogQLFunctionMeta("maxIntersectionsPositionIf", 3, 3, aggregate=True),
    "windowFunnel": HogQLFunctionMeta("windowFunnel", 1, 99, aggregate=True),
    "md5": HogQLFunctionMeta("hex(MD5({}))", 1, 1, aggregate=True, using_placeholder_arguments=True),
}
HOGQL_POSTHOG_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "matchesAction": HogQLFunctionMeta("matchesAction", 1, 1),
    "sparkline": HogQLFunctionMeta("sparkline", 1, 1),
    "recording_button": HogQLFunctionMeta("recording_button", 1, 2),
    "explain_csp_report": HogQLFunctionMeta("explain_csp_report", 1, 1),
    # posthog/models/channel_type/sql.py and posthog/hogql/database/schema/channel_type.py
    "hogql_lookupDomainType": HogQLFunctionMeta("hogql_lookupDomainType", 1, 1),
    "hogql_lookupPaidSourceType": HogQLFunctionMeta("hogql_lookupPaidSourceType", 1, 1),
    "hogql_lookupPaidMediumType": HogQLFunctionMeta("hogql_lookupPaidMediumType", 1, 1),
    "hogql_lookupOrganicSourceType": HogQLFunctionMeta("hogql_lookupOrganicSourceType", 1, 1),
    "hogql_lookupOrganicMediumType": HogQLFunctionMeta("hogql_lookupOrganicMediumType", 1, 1),
    # posthog/models/exchange_rate/sql.py
    # convertCurrency(from_currency, to_currency, amount, timestamp?)
    "convertCurrency": HogQLFunctionMeta(
        "convertCurrency",
        3,
        4,
        signatures=[
            (
                (
                    StringType(),
                    StringType(),
                    DecimalType(),
                ),
                DecimalType(),
            ),
            (
                (
                    StringType(),
                    StringType(),
                    DecimalType(),
                    DateType(),
                ),
                DecimalType(),
            ),
            (
                (
                    StringType(),
                    StringType(),
                    DecimalType(),
                    DateTimeType(),
                ),
                DecimalType(),
            ),
        ],
    ),
}

# The list of functions allowed in parametric functions, e.g. sum in "arrayReduce('sum', [1, 2, 3])"
HOGQL_PERMITTED_PARAMETRIC_FUNCTIONS: set[str] = {
    "count",
    "countMap",
    "countMapState",
    "sum",
    "sumMap",
    "sumMapState",
    "min",
    "minMap",
    "minMapState",
    "max",
    "maxMap",
    "maxMapState",
    "avg",
    "avgState",
    "avgMap",
    "avgMapState",
    "uniq",
    "uniqState",
    "uniqMap",
    "uniqMapState",
}


UDFS: dict[str, HogQLFunctionMeta] = {
    "aggregate_funnel": HogQLFunctionMeta("aggregate_funnel", 6, 6, aggregate=False),
    "aggregate_funnel_array": HogQLFunctionMeta("aggregate_funnel_array", 6, 6, aggregate=False),
    "aggregate_funnel_cohort": HogQLFunctionMeta("aggregate_funnel_cohort", 6, 6, aggregate=False),
    "aggregate_funnel_trends": HogQLFunctionMeta("aggregate_funnel_trends", 8, 8, aggregate=False),
    "aggregate_funnel_array_trends": HogQLFunctionMeta("aggregate_funnel_array_trends", 8, 8, aggregate=False),
    "aggregate_funnel_cohort_trends": HogQLFunctionMeta("aggregate_funnel_cohort_trends", 8, 8, aggregate=False),
    "aggregate_funnel_test": HogQLFunctionMeta("aggregate_funnel_test", 6, 6, aggregate=False),
}
# We want CI to fail if there is a breaking change and the version hasn't been incremented
if is_cloud() or is_ci():
    from posthog.udf_versioner import augment_function_name

    for v in UDFS.values():
        v.clickhouse_name = augment_function_name(v.clickhouse_name)

HOGQL_CLICKHOUSE_FUNCTIONS.update(UDFS)


ALL_EXPOSED_FUNCTION_NAMES = [
    name for name in chain(HOGQL_CLICKHOUSE_FUNCTIONS.keys(), HOGQL_AGGREGATIONS.keys()) if not name.startswith("_")
]

# TODO: Make the below details part of function meta
# Functions where we use a -OrNull variant by default
ADD_OR_NULL_DATETIME_FUNCTIONS = (
    "toDateTime",
    "parseDateTime",
    "parseDateTimeBestEffort",
)
# Functions where the first argument needs to be DateTime and not DateTime64
FIRST_ARG_DATETIME_FUNCTIONS = (
    "tumble",
    "tumbleStart",
    "tumbleEnd",
    "hop",
    "hopStart",
    "hopEnd",
)

SURVEY_FUNCTIONS = {"getSurveyResponse", "uniqueSurveySubmissionsFilter"}


def _find_function(name: str, functions: dict[str, HogQLFunctionMeta]) -> Optional[HogQLFunctionMeta]:
    func = functions.get(name)
    if func is not None:
        return func

    func = functions.get(name.lower())
    if func is None:
        return None
    # If we haven't found a function with the case preserved, but we have found it in lowercase,
    # then the function names are different case-wise only.
    if func.case_sensitive:
        return None

    return func


def find_hogql_aggregation(name: str) -> Optional[HogQLFunctionMeta]:
    return _find_function(name, HOGQL_AGGREGATIONS)


def find_hogql_function(name: str) -> Optional[HogQLFunctionMeta]:
    return _find_function(name, HOGQL_CLICKHOUSE_FUNCTIONS)


def find_hogql_posthog_function(name: str) -> Optional[HogQLFunctionMeta]:
    return _find_function(name, HOGQL_POSTHOG_FUNCTIONS)


def is_allowed_parametric_function(name: str) -> bool:
    # No case-insensitivity for parametric functions
    return name in HOGQL_PERMITTED_PARAMETRIC_FUNCTIONS
