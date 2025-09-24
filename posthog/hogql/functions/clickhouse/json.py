from posthog.hogql.ast import ArrayType, BooleanType, FloatType, IntegerType, StringType, TupleType

from ..core import HogQLFunctionMeta
from ..typegen import generate_json_path_signatures

# json
JSON_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "isValidJSON": HogQLFunctionMeta("isValidJSON", 1, 1, signatures=[((StringType(),), IntegerType())]),
    "JSONHas": HogQLFunctionMeta(
        "JSONHas",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns 1 or 0
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 5 path levels
        ),
    ),
    "JSONLength": HogQLFunctionMeta(
        "JSONLength",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns length as integer
            min_paths=0,  # Can work without paths (root length)
            max_paths=5,  # Up to 5 path levels
        ),
    ),
    "JSONArrayLength": HogQLFunctionMeta(
        "JSONArrayLength",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns array length as integer
            min_paths=0,  # Can work without paths (root array)
            max_paths=5,  # Up to 5 path levels
        ),
    ),
    "JSONType": HogQLFunctionMeta(
        "JSONType",
        1,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=StringType(),  # Returns type name as string
            min_paths=0,  # Can work without paths (root type)
            max_paths=5,  # Up to 5 path levels
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
            min_paths=0,  # Can work without paths (root type)
            max_paths=5,  # Up to 5 path levels
        ),
    ),
    "JSONExtractUInt": HogQLFunctionMeta(
        "JSONExtractUInt",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns unsigned integer
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 4 path levels
        ),
    ),
    "JSONExtractInt": HogQLFunctionMeta(
        "JSONExtractInt",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=IntegerType(),  # Returns signed integer
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 4 path levels
        ),
    ),
    "JSONExtractFloat": HogQLFunctionMeta(
        "JSONExtractFloat",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=FloatType(),  # Returns float
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 4 path levels
        ),
    ),
    "JSONExtractBool": HogQLFunctionMeta(
        "JSONExtractBool",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=BooleanType(),  # Returns boolean
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 4 path levels
        ),
    ),
    "JSONExtractString": HogQLFunctionMeta(
        "JSONExtractString",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=StringType(),  # Returns string
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 4 path levels
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
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],
            return_type=StringType(),
            min_paths=1,
            max_paths=5,
        ),
    ),
    "JSONExtractArrayRaw": HogQLFunctionMeta(
        "JSONExtractArrayRaw",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=StringType(),  # Returns raw JSON array as string
            min_paths=1,  # Requires at least 1 path
            max_paths=5,  # Up to 4 path levels
        ),
    ),
    "JSONExtractKeysAndValues": HogQLFunctionMeta(
        "JSONExtractKeysAndValues",
        1,
        4,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            suffix_types=[StringType()],  # ClickHouse data type as string
            return_type=ArrayType(item_type=TupleType(item_types=[StringType(), StringType()])),
            # Returns array of (key, value) tuples
            min_paths=0,
            max_paths=2,
        ),
    ),
    "JSONExtractKeysAndValuesRaw": HogQLFunctionMeta(
        "JSONExtractKeysAndValuesRaw",
        2,
        6,
        signatures=generate_json_path_signatures(
            fixed_types=[StringType()],  # JSON parameter
            return_type=ArrayType(item_type=TupleType(item_types=[StringType(), StringType()])),
            # Returns array of (key, raw_value) tuples
            min_paths=1,
            max_paths=5,
        ),
    ),
    "JSON_VALUE": HogQLFunctionMeta("JSON_VALUE", 2, 2, signatures=[((StringType(), StringType()), StringType())]),
}
