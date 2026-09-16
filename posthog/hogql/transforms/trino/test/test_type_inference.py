import pytest

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.type_system import infer_function_return_type


@pytest.mark.parametrize(
    "name,arg_types,expected",
    [
        ("medianExact", [ast.IntegerType(nullable=False)], ast.IntegerType(nullable=False)),
        ("medianExactLow", [ast.DateType(nullable=True)], ast.DateType(nullable=True)),
        (
            "medianExactWeightedIf",
            [
                ast.IntegerType(nullable=True),
                ast.IntegerType(nullable=False),
                ast.BooleanType(nullable=False),
            ],
            ast.IntegerType(nullable=True),
        ),
        ("quantileExact", [ast.FloatType(nullable=False)], ast.FloatType(nullable=False)),
        (
            "medianExactHighIf",
            [ast.IntegerType(nullable=False), ast.BooleanType(nullable=True)],
            ast.IntegerType(nullable=False),
        ),
        (
            "avgWeightedIf",
            [ast.IntegerType(nullable=False), ast.FloatType(nullable=True), ast.BooleanType(nullable=False)],
            ast.FloatType(nullable=True),
        ),
        ("skewPop", [ast.IntegerType(nullable=False)], ast.FloatType(nullable=False)),
        (
            "kurtSampIf",
            [ast.FloatType(nullable=True), ast.BooleanType(nullable=False)],
            ast.FloatType(nullable=True),
        ),
        (
            "simpleLinearRegressionIf",
            [
                ast.IntegerType(nullable=False),
                ast.FloatType(nullable=True),
                ast.BooleanType(nullable=False),
            ],
            ast.TupleType(
                nullable=False,
                item_types=[ast.FloatType(nullable=False), ast.FloatType(nullable=False)],
                field_names=["k", "b"],
            ),
        ),
        (
            "maxIntersectionsPositionIf",
            [
                ast.IntegerType(nullable=False),
                ast.IntegerType(nullable=True),
                ast.BooleanType(nullable=False),
            ],
            ast.IntegerType(nullable=True),
        ),
        (
            "groupUniqArrayArrayIf",
            [
                ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=True)),
                ast.BooleanType(nullable=False),
            ],
            ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
        ),
        (
            "groupArrayMovingSumIf",
            [ast.FloatType(nullable=True), ast.BooleanType(nullable=False)],
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        ),
        (
            "groupArrayMovingAvg",
            [ast.IntegerType(nullable=False)],
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        ),
        (
            "deltaSumIf",
            [ast.IntegerType(nullable=True), ast.BooleanType(nullable=False)],
            ast.IntegerType(nullable=False),
        ),
        (
            "groupArrayInsertAtIf",
            [
                ast.StringType(nullable=True),
                ast.IntegerType(nullable=False),
                ast.BooleanType(nullable=False),
            ],
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        ),
        ("roundToExp2", [ast.IntegerType(nullable=True)], ast.IntegerType(nullable=True)),
        (
            "gcd",
            [ast.IntegerType(nullable=False), ast.IntegerType(nullable=True)],
            ast.IntegerType(nullable=True),
        ),
        (
            "arrayAUC",
            [
                ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
                ast.ArrayType(nullable=True, item_type=ast.IntegerType(nullable=False)),
            ],
            ast.FloatType(nullable=True),
        ),
        ("UUIDv7ToDateTime", [ast.UUIDType(nullable=True)], ast.DateTimeType(nullable=True)),
        (
            "tupleToNameValuePairs",
            [
                ast.TupleType(
                    nullable=False,
                    item_types=[ast.IntegerType(nullable=False), ast.FloatType(nullable=True)],
                )
            ],
            ast.ArrayType(
                nullable=False,
                item_type=ast.TupleType(
                    nullable=False,
                    item_types=[ast.StringType(nullable=False), ast.FloatType(nullable=True)],
                ),
            ),
        ),
        (
            "pointInEllipses",
            [ast.FloatType(nullable=False), ast.FloatType(nullable=True)],
            ast.BooleanType(nullable=True),
        ),
        (
            "ifNotFinite",
            [ast.FloatType(nullable=True), ast.IntegerType(nullable=False)],
            ast.FloatType(nullable=True),
        ),
        (
            "mapPopulateSeries",
            [
                ast.MapType(
                    nullable=True,
                    key_type=ast.IntegerType(nullable=False),
                    value_type=ast.StringType(nullable=False),
                )
            ],
            ast.MapType(
                nullable=True,
                key_type=ast.IntegerType(nullable=False),
                value_type=ast.StringType(nullable=False),
            ),
        ),
    ],
)
def test_trino_function_types(name: str, arg_types: list[ast.ConstantType], expected: ast.ConstantType) -> None:
    assert infer_function_return_type(name, arg_types, dialect="trino").return_type == expected


@pytest.mark.parametrize(
    "name",
    [
        "medianMap",
        "medianMapIf",
        "medianMapOrDefault",
        "medianMapOrDefaultIf",
        "medianMapOrNull",
        "medianMapOrNullIf",
    ],
)
def test_resolver_infers_median_map_combinator_types(name: str) -> None:
    arg_types: list[ast.ConstantType] = [
        ast.MapType(
            nullable=False,
            key_type=ast.StringType(nullable=False),
            value_type=ast.IntegerType(nullable=True),
        )
    ]
    if name.endswith("If"):
        arg_types.append(ast.BooleanType(nullable=False))

    assert infer_function_return_type(name, arg_types, dialect="trino").return_type == ast.MapType(
        nullable=False,
        key_type=ast.StringType(nullable=False),
        value_type=ast.FloatType(nullable=False),
    )


@pytest.mark.parametrize(
    "name",
    [
        "medianForEach",
        "medianForEachIf",
        "medianForEachOrDefault",
        "medianForEachOrDefaultIf",
        "medianForEachOrNull",
        "medianForEachOrNullIf",
    ],
)
def test_resolver_infers_median_for_each_combinator_types(name: str) -> None:
    arg_types: list[ast.ConstantType] = [ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=True))]
    if name.endswith("If"):
        arg_types.append(ast.BooleanType(nullable=False))

    assert infer_function_return_type(name, arg_types, dialect="trino").return_type == ast.ArrayType(
        nullable=False,
        item_type=ast.FloatType(nullable=False),
    )


@pytest.mark.parametrize("dialect", ["clickhouse", "hogql", "postgres", "duckdb", "mysql", "snowflake", "redshift"])
@pytest.mark.parametrize(
    "name,arg_types,expected",
    [
        ("medianExact", [ast.IntegerType(nullable=False)], ast.FloatType(nullable=False)),
        (
            "medianForEach",
            [ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False))],
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        ),
        (
            "L2Normalize",
            [ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False))],
            ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
        ),
        ("IPv4StringToNum", [ast.StringType(nullable=False)], ast.UnknownType(unanalyzable=True)),
        ("gcd", [ast.IntegerType(nullable=False), ast.IntegerType(nullable=False)], ast.UnknownType(unanalyzable=True)),
    ],
)
def test_trino_inference_does_not_change_other_dialects(
    name: str, arg_types: list[ast.ConstantType], expected: ast.ConstantType, dialect: HogQLDialect
) -> None:
    assert infer_function_return_type(name, arg_types, dialect=dialect).return_type == expected


@pytest.mark.parametrize(
    "name,arg_types,expected",
    [
        ("isIPv4String", [ast.StringType(nullable=False)], ast.BooleanType(nullable=False)),
        ("isIPv6String", [ast.StringType(nullable=True)], ast.BooleanType(nullable=True)),
        ("IPv4NumToString", [ast.IntegerType(nullable=False)], ast.StringType(nullable=False)),
        ("IPv4StringToNum", [ast.StringType(nullable=False)], ast.IntegerType(nullable=False)),
        ("IPv4StringToNumOrNull", [ast.StringType(nullable=False)], ast.IntegerType(nullable=True)),
    ],
)
def test_trino_network_function_types(name: str, arg_types: list[ast.ConstantType], expected: ast.ConstantType) -> None:
    assert infer_function_return_type(name, arg_types, dialect="trino").return_type == expected
