from posthog.hogql.database.models import (
    DateDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    SavedQuery,
)
from posthog.hogql.database.s3_table import DataWarehouseTable

fields: dict[str, FieldOrTable] = {
    "Date": DateDatabaseField(name="Date"),
    "Open": FloatDatabaseField(name="Open"),
    "High": FloatDatabaseField(name="High"),
    "Low": FloatDatabaseField(name="Low"),
    "Close": FloatDatabaseField(name="Close"),
    "Volume": FloatDatabaseField(name="Volume"),
    "OpenInt": IntegerDatabaseField(name="OpenInt"),
}


def create_aapl_stock_s3_table(name="aapl_stock") -> DataWarehouseTable:
    return DataWarehouseTable(
        name=name,
        url="https://s3.eu-west-3.amazonaws.com/datasets-documentation/aapl_stock.csv",
        format="CSVWithNames",
        fields=fields,
    )


def create_aapl_stock_table_view() -> SavedQuery:
    return SavedQuery(
        id="aapl_stock_view",
        name="aapl_stock_view",
        query="SELECT * FROM aapl_stock",
        fields=fields,
    )


def create_nested_aapl_stock_view() -> SavedQuery:
    return SavedQuery(
        id="aapl_stock_nested_view",
        name="aapl_stock_nested_view",
        query="SELECT * FROM aapl_stock_view",
        fields=fields,
    )


def create_aapl_stock_table_self_referencing() -> SavedQuery:
    return SavedQuery(
        id="aapl_stock_self",
        name="aapl_stock_self",
        query="SELECT * FROM aapl_stock_self",
        fields=fields,
    )
