from posthog.hogql.database.models import DateDatabaseField, IntegerDatabaseField, FloatDatabaseField
from posthog.hogql.database.s3_table import S3Table


def create_aapl_stock_s3_table() -> S3Table:
    return S3Table(
        name="aapl_stock",
        url="https://s3.eu-west-3.amazonaws.com/datasets-documentation/aapl_stock.csv",
        format="CSVWithNames",
        fields={
            "Date": DateDatabaseField(name="Date"),
            "Open": FloatDatabaseField(name="Open"),
            "High": FloatDatabaseField(name="High"),
            "Low": FloatDatabaseField(name="Low"),
            "Close": FloatDatabaseField(name="Close"),
            "Volume": FloatDatabaseField(name="Volume"),
            "OpenInt": IntegerDatabaseField(name="OpenInt"),
        },
    )
