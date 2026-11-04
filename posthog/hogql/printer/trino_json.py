"""Trino SQL builders that reproduce ClickHouse's JSONExtractKeysAndValues value conversions."""

from posthog.dataclasses import frozen


@frozen
class KeysAndValuesType:
    target: str
    # The ClickHouse range a number must fall in, for the integer and Bool types.
    integer_range: tuple[int, int] | None
    nullable: bool


# ClickHouse reads a Bool as a UInt8 and then tests it against zero.
_VALUE_TYPES: dict[str, tuple[str, tuple[int, int] | None]] = {
    "bool": ("BOOLEAN", (0, 255)),
    "float": ("REAL", None),
    "float32": ("REAL", None),
    "float64": ("DOUBLE", None),
    "int": ("INTEGER", (-(2**31), 2**31 - 1)),
    "int8": ("TINYINT", (-(2**7), 2**7 - 1)),
    "int16": ("SMALLINT", (-(2**15), 2**15 - 1)),
    "int32": ("INTEGER", (-(2**31), 2**31 - 1)),
    "int64": ("BIGINT", (-(2**63), 2**63 - 1)),
    "uint8": ("SMALLINT", (0, 2**8 - 1)),
    "uint16": ("INTEGER", (0, 2**16 - 1)),
    "uint32": ("BIGINT", (0, 2**32 - 1)),
    "uint64": ("DECIMAL(20, 0)", (0, 2**64 - 1)),
    "string": ("VARCHAR", None),
}


def parse_keys_and_values_type(type_name: str) -> KeysAndValuesType | None:
    name = type_name.strip()
    nullable = name.lower().startswith("nullable(") and name.endswith(")")
    if nullable:
        name = name[len("nullable(") : -1].strip()
    value_type = _VALUE_TYPES.get(name.lower())
    if value_type is None:
        return None
    target, integer_range = value_type
    return KeysAndValuesType(target=target, integer_range=integer_range, nullable=nullable)


def bind(value: str, name: str, body: str) -> str:
    # Trino has no let-binding, so this names a value for use in body and evaluates it only once.
    return f"element_at(transform(ARRAY[{value}], {name} -> {body}), 1)"


def keys_and_values(document: str, value_type: KeysAndValuesType) -> str:
    """Return the entries of the JSON object `document` as ARRAY(ROW(VARCHAR, target)), in document order."""
    entry = "__hogql_json_entry"
    converted = keys_and_values_value(f"{entry}[2]", value_type)
    # A JSON null is kept as NULL for a Nullable type; every other value that does not convert is dropped.
    kept = f"{entry}.v IS NOT NULL OR {entry}.n" if value_type.nullable else f"{entry}.v IS NOT NULL"
    # CAST to MAP keeps document order, but fails on a duplicate key, so such an object gives an empty array.
    rows = (
        f"transform(map_entries(CAST({document} AS MAP(VARCHAR, JSON))), {entry} -> "
        f"CAST(ROW({entry}[1], {converted}, json_format({entry}[2]) = 'null') "
        f"AS ROW(k VARCHAR, v {value_type.target}, n BOOLEAN)))"
    )
    return f"transform(filter({rows}, {entry} -> {kept}), {entry} -> ROW({entry}.k, {entry}.v))"


def empty_keys_and_values(value_type: KeysAndValuesType) -> str:
    return f"CAST(ARRAY[] AS ARRAY(ROW(VARCHAR, {value_type.target})))"


def keys_and_values_value(value: str, value_type: KeysAndValuesType) -> str:
    text = "__hogql_json_text"
    target = value_type.target
    if target == "VARCHAR":
        converted = (
            f"CASE WHEN starts_with({text}, '\"') THEN CAST({value} AS VARCHAR) "
            f"WHEN regexp_like({text}, '^-?[0-9]') THEN {clickhouse_number_text(text)} "
            f"WHEN {text} <> 'null' THEN {text} END"
        )
        return bind(f"json_format({value})", text, converted)
    # ClickHouse converts a number, a boolean, or a numeric string, and drops anything else.
    number_text = (
        f"CASE json_format({value}) WHEN 'true' THEN '1' WHEN 'false' THEN '0' "
        f"ELSE IF(starts_with(json_format({value}), '\"'), CAST({value} AS VARCHAR), "
        f"IF(regexp_like(json_format({value}), '^-?[0-9]'), json_format({value}))) END"
    )
    if value_type.integer_range is None:
        converted = f"CAST({clickhouse_float(text)} AS {target})"
    elif target == "BOOLEAN":
        converted = f"({clickhouse_integer(text, 'SMALLINT', value_type.integer_range)} <> 0)"
    else:
        converted = clickhouse_integer(text, target, value_type.integer_range)
    return bind(number_text, text, converted)


def clickhouse_float(text: str) -> str:
    return (
        f"CASE WHEN regexp_like({text}, '^[+-]?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?$') "
        f"THEN CAST({text} AS DOUBLE) "
        f"WHEN regexp_like(lower({text}), '^[+-]?inf(inity)?$') "
        f"THEN IF(starts_with({text}, '-'), -infinity(), infinity()) "
        f"WHEN regexp_like(lower({text}), '^[+-]?nan$') THEN nan() END"
    )


def clickhouse_integer(text: str, target: str, integer_range: tuple[int, int]) -> str:
    low, high = integer_range
    number = "__hogql_json_number"
    parsed = (
        f"CAST(ROW(IF(regexp_like({text}, '^[+-]?[0-9]+$'), TRY_CAST({text} AS DECIMAL(38, 0))), "
        f"{clickhouse_float(text)}) AS ROW(i DECIMAL(38, 0), d DOUBLE))"
    )
    # A 64-bit upper bound is not exact as a double, so compare against the next power of two instead.
    upper = f"{number}.d < {high + 1}E0" if high >= 2**63 - 1 else f"{number}.d <= {high}E0"
    truncated = f"CAST(truncate({number}.d) AS {target})"
    if target.startswith("DECIMAL"):
        # Trino casts a DOUBLE to DECIMAL through its shortest decimal text, which rounds large
        # integers, so convert through BIGINT, which is exact.
        truncated = (
            f"IF({number}.d >= {2**63}E0, "
            f"CAST(CAST({number}.d - {2**63}E0 AS BIGINT) AS {target}) + DECIMAL '{2**63}', "
            f"CAST(CAST(truncate({number}.d) AS BIGINT) AS {target}))"
        )
    # ClickHouse reads an integer exactly when it fits in Int64 or UInt64, and reads anything else as a
    # double. A double converts only when it is inside the type's range, and NaN converts to zero.
    converted = (
        f"CASE WHEN {number}.i BETWEEN DECIMAL '{-(2**63)}' AND DECIMAL '{2**64 - 1}' "
        f"THEN IF({number}.i BETWEEN DECIMAL '{low}' AND DECIMAL '{high}', CAST({number}.i AS {target})) "
        f"WHEN is_nan({number}.d) THEN CAST(0 AS {target}) "
        f"WHEN {number}.d >= {low}E0 AND {upper} THEN {truncated} END"
    )
    return bind(parsed, number, converted)


def clickhouse_number_text(text: str) -> str:
    # ClickHouse prints a JSON integer as written and any other number as the shortest text of its double,
    # laid out like JavaScript's Number#toString. Trino prints that double as Java does (1.0E-7), so
    # rebuild the JavaScript layout from its digits and exponent.
    parts = "__hogql_number_parts"
    shape = "__hogql_number_shape"
    shortest = f"CAST(CAST({text} AS DOUBLE) AS VARCHAR)"
    split = (
        f"CAST(ROW(regexp_extract({shortest}, '^-?([0-9]*)', 1), "
        f"coalesce(regexp_extract({shortest}, '\\.([0-9]*)', 1), ''), "
        f"coalesce(CAST(regexp_extract({shortest}, '[eE]([+-]?[0-9]+)$', 1) AS INTEGER), 0)) "
        "AS ROW(i VARCHAR, f VARCHAR, e INTEGER))"
    )
    significant = f"regexp_replace({parts}.i || {parts}.f, '^0+', '')"
    normalized = (
        f"CAST(ROW(regexp_replace({significant}, '0+$', ''), "
        f"length({parts}.i) + {parts}.e - length({parts}.i || {parts}.f) + length({significant})) "
        "AS ROW(d VARCHAR, n INTEGER))"
    )
    digits, point, size = f"{shape}.d", f"{shape}.n", f"length({shape}.d)"
    layout = (
        f"CASE WHEN {digits} = '' THEN '0' "
        f"WHEN {size} <= {point} AND {point} <= 21 THEN {digits} || lpad('', {point} - {size}, '0') "
        f"WHEN 0 < {point} AND {point} <= 21 THEN substr({digits}, 1, {point}) || '.' || substr({digits}, {point} + 1) "
        f"WHEN -6 < {point} AND {point} <= 0 THEN '0.' || lpad('', -{point}, '0') || {digits} "
        f"ELSE substr({digits}, 1, 1) || IF({size} > 1, '.' || substr({digits}, 2), '') "
        f"|| 'e' || CAST({point} - 1 AS VARCHAR) END"
    )
    signed = f"IF(starts_with({text}, '-') AND {digits} <> '', '-', '') || {layout}"
    return f"IF(regexp_like({text}, '^-?[0-9]+$'), {text}, {bind(split, parts, bind(normalized, shape, signed))})"
