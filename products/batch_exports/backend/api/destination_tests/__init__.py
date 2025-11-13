from products.batch_exports.backend.api.destination_tests.base import DestinationTest
from products.batch_exports.backend.api.destination_tests.bigquery import BigQueryDestinationTest
from products.batch_exports.backend.api.destination_tests.databricks import DatabricksDestinationTest
from products.batch_exports.backend.api.destination_tests.s3 import S3DestinationTest
from products.batch_exports.backend.api.destination_tests.snowflake import SnowflakeDestinationTest


def get_destination_test(
    destination: str,
) -> DestinationTest:
    """Resolve a destination to its corresponding `DestinationTest` implementation."""
    if destination == "S3":
        return S3DestinationTest()
    elif destination == "BigQuery":
        return BigQueryDestinationTest()
    elif destination == "Snowflake":
        return SnowflakeDestinationTest()
    elif destination == "Databricks":
        return DatabricksDestinationTest()
    else:
        raise ValueError(f"Unsupported destination: {destination}")
