"""Polymorphic destination schemas for API requests and responses."""

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from . import azure_blob, bigquery, databricks, postgres, redshift, s3, snowflake


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="BatchExportDestinationConfig",
        serializers={
            "Databricks": databricks.DatabricksDestinationConfigSerializer,
            "AzureBlob": azure_blob.AzureBlobDestinationConfigSerializer,
            "BigQuery": bigquery.BigQueryDestinationConfigSerializer,
            "Postgres": postgres.PostgresDestinationConfigSerializer,
            "AwsS3": s3.AwsS3DestinationConfigSerializer,
            "S3Compatible": s3.S3CompatibleDestinationConfigSerializer,
            "Snowflake": snowflake.SnowflakeDestinationConfigSerializer,
            "Redshift": redshift.RedshiftDestinationConfigSerializer,
        },
        resource_type_field_name="type",
    )
)
class TypedBatchExportDestinationConfigField(serializers.JSONField):
    """JSONField with a polymorphic OpenAPI schema keyed by the sibling `type`.

    Runtime validation remains a plain JSONField (see
    `BatchExportDestinationSerializer.validate`); the decorator only shapes the
    generated OpenAPI spec so clients and MCP tools see typed configs for
    integration-backed destinations.
    """

    pass


BatchExportDestinationRequest = PolymorphicProxySerializer(
    component_name="BatchExportDestinationRequest",
    serializers={
        "Databricks": databricks.DatabricksDestinationRequestSerializer,
        "AzureBlob": azure_blob.AzureBlobDestinationRequestSerializer,
        "BigQuery": bigquery.BigQueryDestinationRequestSerializer,
        "Postgres": postgres.PostgresDestinationRequestSerializer,
        "AwsS3": s3.AwsS3DestinationRequestSerializer,
        "S3Compatible": s3.S3CompatibleDestinationRequestSerializer,
        "Snowflake": snowflake.SnowflakeDestinationRequestSerializer,
        "Redshift": redshift.RedshiftDestinationRequestSerializer,
    },
    resource_type_field_name="type",
)


@extend_schema_field(BatchExportDestinationRequest)
class BatchExportDestinationRequestField(serializers.JSONField):
    """JSONField annotated with a polymorphic OpenAPI request schema.

    Only integration-backed destinations (Databricks, AzureBlob, BigQuery, Postgres, AwsS3,
    S3Compatible, Snowflake, Redshift) are exposed in the schema. integration_id is required for
    every one of them. Existing Postgres and Redshift exports created before integrations keep
    their inline credentials and stay valid when edited. Runtime validation remains
    `BatchExportSerializer.validate_destination`, which dispatches to each destination's validator.
    """

    pass
