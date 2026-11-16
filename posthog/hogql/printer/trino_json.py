"""Calls to the PostHog Trino functions that reproduce ClickHouse's JSONExtractKeysAndValues."""

import json

from posthog.dataclasses import frozen


@frozen
class KeysAndValuesType:
    # The suffix of the ch_json_extract_keys_and_values_* function for this type.
    function: str
    # The narrower Trino integer type to cast the function's BIGINT values to, if any.
    cast: str | None
    # The ClickHouse range a number must fall in, for the ch_..._int function.
    integer_range: tuple[int, int] | None
    nullable: bool


_VALUE_TYPES: dict[str, tuple[str, str | None, tuple[int, int] | None]] = {
    "bool": ("bool", None, None),
    "float": ("float32", None, None),
    "float32": ("float32", None, None),
    "float64": ("float64", None, None),
    "int": ("int", "INTEGER", (-(2**31), 2**31 - 1)),
    "int8": ("int", "TINYINT", (-(2**7), 2**7 - 1)),
    "int16": ("int", "SMALLINT", (-(2**15), 2**15 - 1)),
    "int32": ("int", "INTEGER", (-(2**31), 2**31 - 1)),
    "int64": ("int", None, (-(2**63), 2**63 - 1)),
    "uint8": ("int", "SMALLINT", (0, 2**8 - 1)),
    "uint16": ("int", "INTEGER", (0, 2**16 - 1)),
    "uint32": ("int", None, (0, 2**32 - 1)),
    "uint64": ("uint64", None, None),
    "string": ("string", None, None),
}


def parse_keys_and_values_type(type_name: str) -> KeysAndValuesType | None:
    name = type_name.strip()
    nullable = name.lower().startswith("nullable(") and name.endswith(")")
    if nullable:
        name = name[len("nullable(") : -1].strip()
    value_type = _VALUE_TYPES.get(name.lower())
    if value_type is None:
        return None
    function, cast, integer_range = value_type
    return KeysAndValuesType(function=function, cast=cast, integer_range=integer_range, nullable=nullable)


def keys_and_values_path(path: list[str | int]) -> str:
    """The path argument of the ch_json_extract_keys_and_values_* functions: a JSON array of keys and indexes."""
    return json.dumps(path, ensure_ascii=False)


def keys_and_values(source: str, path: str, value_type: KeysAndValuesType) -> str:
    # The functions read JSON text. A native JSON value cannot be cast to VARCHAR when it holds an object,
    # and the HogQL type cannot tell it from a JSON string, so choose by the runtime type.
    document = f"IF(typeof({source}) = 'json', json_format(json_extract({source}, '$')), CAST({source} AS VARCHAR))"
    arguments = f"{document}, {path}, {'true' if value_type.nullable else 'false'}"
    if value_type.integer_range is not None:
        low, high = value_type.integer_range
        # BIGINT has no literal for its minimum value.
        low_sql = f"{low + 1} - 1" if low == -(2**63) else str(low)
        arguments += f", {low_sql}, {high}"
    call = f"ch_json_extract_keys_and_values_{value_type.function}({arguments})"
    if value_type.cast is None:
        return call
    # The function already applied the type's range, so this cast cannot fail.
    return f"CAST({call} AS ARRAY(ROW(VARCHAR, {value_type.cast})))"
