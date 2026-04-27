import re
import socket
from ipaddress import IPv6Address, ip_address
from typing import TYPE_CHECKING, Any, Protocol, Union
from urllib.parse import urlparse

from django.db.models import Q

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    StructDatabaseField,
    UnknownDatabaseField,
)

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseTable


class DatabaseFieldFactory(Protocol):
    __name__: str

    def __call__(self, *args: Any, **kwargs: Any) -> DatabaseField: ...


def get_view_or_table_by_name(team, name) -> Union["DataWarehouseSavedQuery", "DataWarehouseTable", None]:
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseTable

    table_names = [name]
    if "." in name:
        chain = name.split(".")
        if len(chain) == 2:
            table_names = [f"{chain[0]}_{chain[1]}"]
        elif len(chain) == 3:
            # Support both `_` suffixed source prefix and without - e.g. postgres_table_name and postgrestable_name
            table_names = [f"{chain[1]}_{chain[0]}_{chain[2]}", f"{chain[1]}{chain[0]}_{chain[2]}"]

    table: DataWarehouseSavedQuery | DataWarehouseTable | None = (
        DataWarehouseTable.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
        .filter(team=team, name__in=table_names)
        .first()
    )
    if table is None:
        table = DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(team=team, name=name).first()
    return table


def validate_source_prefix(prefix: str | None) -> tuple[bool, str]:
    """
    Validate that prefix will form valid HogQL/ClickHouse identifiers.

    Valid prefixes must:
    - Contain only letters, numbers, and underscores
    - Start with a letter or underscore
    - Not be empty after stripping underscores

    Returns:
        tuple[bool, str]: (is_valid, error_message)
    """
    if not prefix:
        return True, ""  # Empty/None prefix is allowed

    # Strip underscores that will be stripped during table name construction
    cleaned = prefix.strip("_")

    if not cleaned:
        return False, "Prefix cannot consist of only underscores"

    # Check if prefix matches HogQL identifier rules
    # Must start with letter or underscore, contain only letters, digits, underscores
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", cleaned):
        return (
            False,
            "Prefix must contain only letters, numbers, and underscores, and start with a letter or underscore",
        )

    return True, ""


def remove_named_tuples(type):
    """Remove named tuples from query"""
    from products.data_warehouse.backend.models.table import CLICKHOUSE_HOGQL_MAPPING

    tokenified_type = re.split(r"(\W)", type)
    filtered_tokens = []
    i = 0
    while i < len(tokenified_type):
        token = tokenified_type[i]
        # handle tokenization of DateTime types that need to be parsed in a specific way ie) DateTime64(3, 'UTC')
        if token == "DateTime64" or token == "DateTime32":
            filtered_tokens.append(token)
            i += 1
            if i < len(tokenified_type) and tokenified_type[i] == "(":
                filtered_tokens.append(tokenified_type[i])
                i += 1
                while i < len(tokenified_type) and tokenified_type[i] != ")":
                    if tokenified_type[i] == "'":
                        filtered_tokens.append(tokenified_type[i])
                        i += 1
                        while i < len(tokenified_type) and tokenified_type[i] != "'":
                            filtered_tokens.append(tokenified_type[i])
                            i += 1
                        if i < len(tokenified_type):
                            filtered_tokens.append(tokenified_type[i])
                    else:
                        filtered_tokens.append(tokenified_type[i])
                    i += 1
                if i < len(tokenified_type):
                    filtered_tokens.append(tokenified_type[i])
        elif token == "`":
            # Skip backtick-quoted identifiers (field names like `1`, `deal_id`)
            i += 1
            while i < len(tokenified_type) and tokenified_type[i] != "`":
                i += 1
            # Skip closing backtick
        elif (
            token == "Nullable" or (len(token) == 1 and not token.isalnum()) or token in CLICKHOUSE_HOGQL_MAPPING.keys()
        ):
            filtered_tokens.append(token)
        i += 1
    return "".join(filtered_tokens)


def clean_type(column_type: str) -> str:
    # Replace newline characters followed by empty space
    column_type = re.sub(r"\n\s+", "", column_type)

    if column_type.startswith("Nullable("):
        column_type = column_type.replace("Nullable(", "")[:-1]

    if column_type.startswith("Array("):
        column_type = remove_named_tuples(column_type)

    column_type = re.sub(r"\(.+\)+", "", column_type)

    return column_type


CLICKHOUSE_HOGQL_MAPPING: dict[str, DatabaseFieldFactory] = {
    "UUID": StringDatabaseField,
    "String": StringDatabaseField,
    "Nothing": UnknownDatabaseField,
    "DateTime64": DateTimeDatabaseField,
    "DateTime32": DateTimeDatabaseField,
    "DateTime": DateTimeDatabaseField,
    "Date": DateDatabaseField,
    "Date32": DateDatabaseField,
    "UInt8": IntegerDatabaseField,
    "UInt16": IntegerDatabaseField,
    "UInt32": IntegerDatabaseField,
    "UInt64": IntegerDatabaseField,
    "Float8": FloatDatabaseField,
    "Float16": FloatDatabaseField,
    "Float32": FloatDatabaseField,
    "Float64": FloatDatabaseField,
    "Int8": IntegerDatabaseField,
    "Int16": IntegerDatabaseField,
    "Int32": IntegerDatabaseField,
    "Int64": IntegerDatabaseField,
    "Tuple": StringJSONDatabaseField,
    "Array": StringArrayDatabaseField,
    "Map": StringJSONDatabaseField,
    "Bool": BooleanDatabaseField,
    "Decimal": DecimalDatabaseField,
    "FixedString": StringDatabaseField,
    "Enum8": StringDatabaseField,
}

STR_TO_HOGQL_MAPPING: dict[str, DatabaseFieldFactory] = {
    "BooleanDatabaseField": BooleanDatabaseField,
    "DateDatabaseField": DateDatabaseField,
    "DateTimeDatabaseField": DateTimeDatabaseField,
    "IntegerDatabaseField": IntegerDatabaseField,
    "DecimalDatabaseField": DecimalDatabaseField,
    "FloatDatabaseField": FloatDatabaseField,
    "StringArrayDatabaseField": StringArrayDatabaseField,
    "StringDatabaseField": StringDatabaseField,
    "StringJSONDatabaseField": StringJSONDatabaseField,
    "StructDatabaseField": StructDatabaseField,
    "UnknownDatabaseField": UnknownDatabaseField,
    "boolean": BooleanDatabaseField,
    "date": DateDatabaseField,
    "datetime": DateTimeDatabaseField,
    "timestamp": DateTimeDatabaseField,
    "integer": IntegerDatabaseField,
    "numeric": DecimalDatabaseField,
    "decimal": DecimalDatabaseField,
    "float": FloatDatabaseField,
    "string": StringDatabaseField,
    "text": StringDatabaseField,
    "array": StringArrayDatabaseField,
    "json": StringJSONDatabaseField,
    "struct": StructDatabaseField,
    "unknown": UnknownDatabaseField,
}


POSTGRES_TO_CLICKHOUSE_TYPE = {
    "smallint": "Int16",
    "integer": "Int32",
    "bigint": "Int64",
    "real": "Float32",
    "double precision": "Float64",
    "numeric": "Decimal",
    "decimal": "Decimal",
    "boolean": "Bool",
    "date": "Date",
    "timestamp without time zone": "DateTime64",
    "timestamp with time zone": "DateTime64",
    "character varying": "String",
    "character": "String",
    "text": "String",
    "json": "String",
    "jsonb": "String",
    "uuid": "String",
}


CLICKHOUSE_TYPE_TO_HOGQL_LABEL = {
    "Int16": "integer",
    "Int32": "integer",
    "Int64": "integer",
    "Float32": "float",
    "Float64": "float",
    "Bool": "boolean",
    "Date": "date",
    "DateTime64": "datetime",
    "String": "string",
    "Decimal": "numeric",
}


def _split_top_level_items(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0

    while i < len(value):
        char = value[i]

        if quote is not None:
            current.append(char)
            if char == quote:
                next_char = value[i + 1] if i + 1 < len(value) else None
                if next_char == quote:
                    current.append(next_char)
                    i += 1
                else:
                    quote = None
            i += 1
            continue

        if char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(depth - 1, 0)
            current.append(char)
        elif char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(char)

        i += 1

    final_item = "".join(current).strip()
    if final_item:
        items.append(final_item)

    return items


def _parse_struct_field(field: str) -> tuple[str, str] | None:
    field = field.strip()
    if not field:
        return None

    if field.startswith('"'):
        identifier: list[str] = []
        i = 1
        while i < len(field):
            char = field[i]
            if char == '"':
                if i + 1 < len(field) and field[i + 1] == '"':
                    identifier.append('"')
                    i += 2
                    continue
                break
            identifier.append(char)
            i += 1

        if i >= len(field):
            return None

        field_name = "".join(identifier)
        field_type = field[i + 1 :].strip()
    else:
        parts = field.split(None, 1)
        if len(parts) != 2:
            return None
        field_name, field_type = parts

    if not field_type:
        return None

    return field_name, field_type


def _parse_postgres_struct_fields(postgres_type: str) -> dict[str, dict[str, Any]] | None:
    match = re.match(r"(?is)^struct\s*\((.*)\)$", postgres_type.strip())
    if match is None:
        return None

    fields: dict[str, dict[str, Any]] = {}
    for field in _split_top_level_items(match.group(1)):
        parsed_field = _parse_struct_field(field)
        if parsed_field is None:
            return None

        field_name, field_type = parsed_field
        fields[field_name] = postgres_column_to_dwh_column(field_name, field_type, False)

    return fields


def postgres_column_to_dwh_column(_column_name: str, postgres_type: str, nullable: bool) -> dict[str, Any]:
    struct_fields = _parse_postgres_struct_fields(postgres_type)
    if struct_fields is not None:
        struct_clickhouse_type = f"Tuple({', '.join(str(field['clickhouse']) for field in struct_fields.values())})"
        if nullable:
            struct_clickhouse_type = f"Nullable({struct_clickhouse_type})"

        return {
            "clickhouse": struct_clickhouse_type,
            "hogql": "StructDatabaseField",
            "valid": True,
            "fields": struct_fields,
        }

    normalized_type = postgres_type.lower()
    clickhouse_type: str | None = POSTGRES_TO_CLICKHOUSE_TYPE.get(normalized_type)

    if clickhouse_type is None:
        if normalized_type.startswith("timestamp"):
            clickhouse_type = "DateTime64"
        elif normalized_type.startswith("numeric") or normalized_type.startswith("decimal"):
            clickhouse_type = "Decimal"
        elif "int" in normalized_type:
            clickhouse_type = "Int64"
        else:
            clickhouse_type = "String"

    if nullable:
        clickhouse_type = f"Nullable({clickhouse_type})"

    raw_clickhouse_type = clean_type(clickhouse_type)
    return {
        "clickhouse": clickhouse_type,
        "hogql": CLICKHOUSE_TYPE_TO_HOGQL_LABEL.get(raw_clickhouse_type, "string"),
        "valid": True,
    }


def postgres_columns_to_dwh_columns(columns: list[tuple[str, str, bool]]) -> dict[str, dict[str, Any]]:
    return {
        column_name: postgres_column_to_dwh_column(column_name, postgres_type, nullable)
        for column_name, postgres_type, nullable in columns
    }


def _is_safe_public_ip(host: str) -> bool:
    ip = ip_address(host)

    # IPv6 can carry embedded IPv4 addresses that need the same SSRF checks.
    if isinstance(ip, IPv6Address):
        if ip.ipv4_mapped:
            return _is_safe_public_ip(str(ip.ipv4_mapped))
        if ip.sixtofour:
            return _is_safe_public_ip(str(ip.sixtofour))

    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def validate_warehouse_table_url_pattern(url_pattern: str | None) -> tuple[bool, str]:
    if not url_pattern:
        return True, ""

    parsed = urlparse(url_pattern)
    if parsed.scheme != "https":
        return False, "URL pattern must use https."

    if not parsed.hostname:
        return False, "URL pattern must include a valid hostname."

    normalized_hostname = parsed.hostname.lower().strip().rstrip(".")
    if normalized_hostname in {"localhost"}:
        return False, "URL pattern hostname is not allowed."

    # Block direct internal IP literals.
    try:
        if not _is_safe_public_ip(parsed.hostname):
            return False, "URL pattern hostname must not resolve to internal IP ranges."
    except ValueError:
        pass

    # Resolve the hostname and block if any resolved IP is internal (catches DNS rebinding services).
    try:
        addrinfo = socket.getaddrinfo(normalized_hostname, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in addrinfo:
            resolved_ip = sockaddr[0]
            if not _is_safe_public_ip(str(resolved_ip)):
                return False, "URL pattern hostname must not resolve to internal IP ranges."
    except socket.gaierror:
        return False, "URL pattern hostname could not be resolved."

    return True, ""
