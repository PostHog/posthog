from products.batch_exports.backend.destination_tests.base import DestinationTest


def get_destination_test(
    destination: str,
) -> DestinationTest:
    """Resolve a destination to its corresponding `DestinationTest` implementation.

    Per-branch deferred imports: each destination test module pulls a heavy vendor SDK
    (databricks, google-cloud-bigquery, snowflake, etc.). Importing them lazily keeps the
    SDKs off the API import path — only the requested destination's SDK loads.
    """
    if destination == "S3Compatible":
        from products.batch_exports.backend.destination_tests.s3 import S3CompatibleDestinationTest  # noqa: PLC0415

        return S3CompatibleDestinationTest()
    elif destination == "AwsS3":
        from products.batch_exports.backend.destination_tests.s3 import AwsS3DestinationTest  # noqa: PLC0415

        return AwsS3DestinationTest()
    elif destination == "BigQuery":
        from products.batch_exports.backend.destination_tests.bigquery import BigQueryDestinationTest  # noqa: PLC0415

        return BigQueryDestinationTest()
    elif destination == "Snowflake":
        from products.batch_exports.backend.destination_tests.snowflake import SnowflakeDestinationTest  # noqa: PLC0415

        return SnowflakeDestinationTest()
    elif destination == "Databricks":
        from products.batch_exports.backend.destination_tests.databricks import (  # noqa: PLC0415
            DatabricksDestinationTest,
        )

        return DatabricksDestinationTest()
    elif destination == "AzureBlob":
        from products.batch_exports.backend.destination_tests.azure_blob import (  # noqa: PLC0415
            AzureBlobDestinationTest,
        )

        return AzureBlobDestinationTest()
    else:
        raise ValueError(f"Unsupported destination: {destination}")
