from posthog.hogql.ast import DateTimeType, DecimalType, FloatType, IntegerType, IntervalType, TupleType

from ..core import HogQLFunctionMeta

# arithmetic
ARITHMETIC_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
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
}
