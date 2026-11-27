import re

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

# The functions that take the document first and then a key path. On the native events table, a call with a constant
# first key reads that key's subcolumn instead of the whole rebuilt document (`PropertySwapper._rewrite_json_property_call`).
# The excluded functions take no key path (`isValidJSON`, `JSONArrayLength`) or a JSONPath string (`JSON_VALUE`).
JSON_KEY_PATH_FUNCTIONS = frozenset(JSON_FUNCTIONS) - {"isValidJSON", "JSONArrayLength", "JSON_VALUE"}
# Key-path functions whose last argument is the ClickHouse type to extract, so the key path ends before it.
JSON_TYPED_PATH_FUNCTIONS = frozenset({"JSONExtract", "JSONExtractKeysAndValues"})

_TYPE_NAME_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# ClickHouse reads a type name of more than one word only for SQL-standard and MySQL spellings,
# such as DOUBLE PRECISION, NATIONAL CHAR VARYING, BINARY LARGE OBJECT and INT(11) UNSIGNED.
_TYPE_NAME_MODIFIER_WORDS = frozenset(
    {"PRECISION", "VARYING", "LARGE", "OBJECT", "CHAR", "CHARACTER", "SIGNED", "UNSIGNED"}
)


def looks_like_clickhouse_type_name(type_name: str) -> bool:
    """Whether ClickHouse can parse the text as a data type. Only the outer level is checked: the text in
    parentheses goes to ClickHouse as is, and ClickHouse decides if the type exists."""
    words: list[str] = []
    current = ""
    depth = 0
    quote: str | None = None
    escaped = False
    for char in type_name:
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'`\"":
            if depth == 0:
                # A quoted identifier can start the outer name. A string literal cannot be one.
                if char == "'" or current:
                    return False
                current = "_"
            quote = char
        elif char == "(":
            if depth == 0:
                if current:
                    words.append(current)
                    current = ""
                elif not words:
                    return False
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
        elif depth > 0:
            continue
        elif char.isspace():
            if current:
                words.append(current)
                current = ""
        else:
            current += char
    if quote is not None or depth != 0:
        return False
    if current:
        words.append(current)
    if not words or not _TYPE_NAME_WORD.fullmatch(words[0]):
        return False
    return all(word.upper() in _TYPE_NAME_MODIFIER_WORDS for word in words[1:])
