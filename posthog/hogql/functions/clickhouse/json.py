from posthog.hogql.ast import ArrayType, BooleanType, FloatType, IntegerType, StringType, TupleType

from ..core import HogQLFunctionMeta
from ..typegen import generate_json_path_signatures

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
JSON_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "isValidJSON": HogQLFunctionMeta("isValidJSON", 1, 1, signatures=[((StringType(),), IntegerType())]),
    "JSONHas": HogQLFunctionMeta(
        "JSONHas",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns 1 or 0
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONLength": HogQLFunctionMeta(
        "JSONLength",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns length as integer
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONArrayLength": HogQLFunctionMeta(
        "JSONArrayLength",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns array length as integer
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONType": HogQLFunctionMeta(
        "JSONType",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=StringType(),  # Returns type name as string
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtract": HogQLFunctionMeta(
        "JSONExtract",
        2,
        7,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            suffix_types=[StringType()],  # ClickHouse data type as string
            return_type=StringType(),  # Returns type name as string
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractUInt": HogQLFunctionMeta(
        "JSONExtractUInt",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns unsigned integer
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractInt": HogQLFunctionMeta(
        "JSONExtractInt",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns signed integer
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractFloat": HogQLFunctionMeta(
        "JSONExtractFloat",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=FloatType(),  # Returns float
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractBool": HogQLFunctionMeta(
        "JSONExtractBool",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=BooleanType(),  # Returns boolean
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractString": HogQLFunctionMeta(
        "JSONExtractString",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=StringType(),  # Returns string
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractKeys": HogQLFunctionMeta(
        "JSONExtractKeys",
        1,
        5,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=ArrayType(item_type=StringType()),  # Returns array of key names
            min_paths=0,
            max_paths=4,
        ),
    ),
    "JSONExtractRaw": HogQLFunctionMeta(
        "JSONExtractRaw",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],
            return_type=StringType(),
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractArrayRaw": HogQLFunctionMeta(
        "JSONExtractArrayRaw",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=StringType(),  # Returns raw JSON array as string
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractKeysAndValues": HogQLFunctionMeta(
        "JSONExtractKeysAndValues",
        2,
        7,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            suffix_types=[StringType()],  # ClickHouse data type as string
            return_type=ArrayType(item_type=TupleType(item_types=[StringType(), StringType()])),
            # Returns array of (key, value) tuples
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSONExtractKeysAndValuesRaw": HogQLFunctionMeta(
        "JSONExtractKeysAndValuesRaw",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=ArrayType(item_type=TupleType(item_types=[StringType(), StringType()])),
            # Returns array of (key, raw_value) tuples
            min_paths=0,
            max_paths=5,
        ),
    ),
    "JSON_VALUE": HogQLFunctionMeta("JSON_VALUE", 2, 2, signatures=[((StringType(), StringType()), StringType())]),
}
