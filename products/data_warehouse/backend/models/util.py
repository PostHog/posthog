import re
from typing import TYPE_CHECKING, Union

from django.db.models import Q

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    UnknownDatabaseField,
)

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseTable


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


CLICKHOUSE_HOGQL_MAPPING = {
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

STR_TO_HOGQL_MAPPING = {
    "BooleanDatabaseField": BooleanDatabaseField,
    "DateDatabaseField": DateDatabaseField,
    "DateTimeDatabaseField": DateTimeDatabaseField,
    "IntegerDatabaseField": IntegerDatabaseField,
    "DecimalDatabaseField": DecimalDatabaseField,
    "FloatDatabaseField": FloatDatabaseField,
    "StringArrayDatabaseField": StringArrayDatabaseField,
    "StringDatabaseField": StringDatabaseField,
    "StringJSONDatabaseField": StringJSONDatabaseField,
    "UnknownDatabaseField": UnknownDatabaseField,
}
