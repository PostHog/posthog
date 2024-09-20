import re

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)


def remove_named_tuples(type):
    """Remove named tuples from query"""
    from posthog.warehouse.models.table import CLICKHOUSE_HOGQL_MAPPING

    tokenified_type = re.split(r"(\W)", type)
    filtered_tokens = [
        token
        for token in tokenified_type
        if token == "Nullable" or (len(token) == 1 and not token.isalnum()) or token in CLICKHOUSE_HOGQL_MAPPING.keys()
    ]
    return "".join(filtered_tokens)


def clean_type(column_type: str) -> str:
    if column_type.startswith("Nullable("):
        column_type = column_type.replace("Nullable(", "")[:-1]

    if column_type.startswith("Array("):
        column_type = remove_named_tuples(column_type)

    column_type = re.sub(r"\(.+\)+", "", column_type)

    return column_type


CLICKHOUSE_HOGQL_MAPPING = {
    "UUID": StringDatabaseField,
    "String": StringDatabaseField,
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
    "Decimal": FloatDatabaseField,
}

STR_TO_HOGQL_MAPPING = {
    "BooleanDatabaseField": BooleanDatabaseField,
    "DateDatabaseField": DateDatabaseField,
    "DateTimeDatabaseField": DateTimeDatabaseField,
    "IntegerDatabaseField": IntegerDatabaseField,
    "FloatDatabaseField": FloatDatabaseField,
    "StringArrayDatabaseField": StringArrayDatabaseField,
    "StringDatabaseField": StringDatabaseField,
    "StringJSONDatabaseField": StringJSONDatabaseField,
}
