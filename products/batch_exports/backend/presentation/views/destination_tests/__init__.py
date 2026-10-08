from products.batch_exports.backend.presentation.views.destination_tests.base import DestinationTest


def get_destination_test(
    destination: str,
) -> DestinationTest:
    """Resolve a destination to its corresponding `DestinationTest` implementation.

    Per-branch deferred imports: each destination test module pulls a heavy vendor SDK
    (databricks, google-cloud-bigquery, snowflake, etc.). Importing them lazily keeps the
    SDKs off the API import path — only the requested destination's SDK loads.
    """
    if destination == "S3Compatible":
        from products.batch_exports.backend.presentation.views.destination_tests.s3 import (  # noqa: PLC0415
            S3CompatibleDestinationTest,
        )

        return S3CompatibleDestinationTest()
    elif destination == "AwsS3":
        from products.batch_exports.backend.presentation.views.destination_tests.s3 import (  # noqa: PLC0415
            AwsS3DestinationTest,
        )

        return AwsS3DestinationTest()
    elif destination == "BigQuery":
        from products.batch_exports.backend.presentation.views.destination_tests.bigquery import (  # noqa: PLC0415
            BigQueryDestinationTest,
        )

        return BigQueryDestinationTest()
    elif destination == "Snowflake":
        from products.batch_exports.backend.presentation.views.destination_tests.snowflake import (  # noqa: PLC0415
            SnowflakeDestinationTest,
        )

        return SnowflakeDestinationTest()
    elif destination == "Databricks":
        from products.batch_exports.backend.presentation.views.destination_tests.databricks import (  # noqa: PLC0415
            DatabricksDestinationTest,
        )

        return DatabricksDestinationTest()
    elif destination == "AzureBlob":
        from products.batch_exports.backend.presentation.views.destination_tests.azure_blob import (  # noqa: PLC0415
            AzureBlobDestinationTest,
        )

        return AzureBlobDestinationTest()
    else:
        raise ValueError(f"Unsupported destination: {destination}")
