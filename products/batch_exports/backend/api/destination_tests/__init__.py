from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.batch_exports.backend.api.destination_tests.base import DestinationTest


def get_destination_test(
    destination: str,
) -> "DestinationTest":
    """Resolve a destination to its corresponding `DestinationTest` implementation."""
    if destination == "S3":
        from products.batch_exports.backend.api.destination_tests.s3 import S3DestinationTest

        return S3DestinationTest()
    elif destination == "BigQuery":
        from products.batch_exports.backend.api.destination_tests.bigquery import BigQueryDestinationTest

        return BigQueryDestinationTest()
    elif destination == "Snowflake":
        from products.batch_exports.backend.api.destination_tests.snowflake import SnowflakeDestinationTest

        return SnowflakeDestinationTest()
    elif destination == "Databricks":
        from products.batch_exports.backend.api.destination_tests.databricks import DatabricksDestinationTest

        return DatabricksDestinationTest()
    else:
        raise ValueError(f"Unsupported destination: {destination}")
