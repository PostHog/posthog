"""Batch export destination serializers: the typed config and request shape of each destination type."""

import typing

from django.db import models

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from posthog.integrations.fields import IntegrationReferenceField

from products.batch_exports.backend.facade import api as batch_exports_api
from products.batch_exports.backend.facade.contracts import InvalidDestinationConfigError
from products.batch_exports.backend.facade.enums import (
    AZURE_BLOB_SUPPORTED_COMPRESSIONS,
    BATCH_EXPORT_INTEGRATION_KINDS,
    S3_SUPPORTED_COMPRESSIONS,
    BatchExportDestinationType,
)


class DatabricksDestinationConfigSerializer(serializers.Serializer):
    """Typed configuration for a Databricks batch-export destination.

    Credentials live in the linked Integration, not in this config. Mirrors
    `DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.
    """

    http_path = serializers.CharField(help_text="Databricks SQL warehouse HTTP path.")
    catalog = serializers.CharField(help_text="Unity Catalog name.")
    schema = serializers.CharField(help_text="Schema (database) name inside the catalog.")
    table_name = serializers.CharField(help_text="Destination table name.")
    use_variant_type = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to use the Databricks VARIANT type for JSON-like columns.",
    )
    use_automatic_schema_evolution = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to let Databricks evolve the destination table schema automatically.",
    )


class BigQueryDestinationConfigSerializer(serializers.Serializer):
    """Typed configuration for a BigQuery batch-export destination.

    Credentials live in the linked Integration, not in this config. Mirrors the
    non-credential fields of `BigQueryBatchExportInputs` in
    `products/batch_exports/backend/service.py`.
    """

    dataset_id = serializers.CharField(help_text="BigQuery dataset ID to write to.")
    table_id = serializers.CharField(
        required=False,
        default="events",
        help_text="BigQuery table ID inside the dataset.",
    )
    use_json_type = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether to export 'properties', 'set', and 'set_once' fields as the BigQuery JSON type "
            "rather than STRING. Cannot be changed after the export is created."
        ),
    )


class PostgresDestinationConfigSerializer(serializers.Serializer):
    """Typed configuration for a PostgreSQL batch-export destination.

    Connection credentials may live in a linked Integration (when one is provided) or
    inline in this config (legacy). Mirrors the non-credential fields of
    `PostgresBatchExportInputs` in `products/batch_exports/backend/service.py`.
    """

    database = serializers.CharField(help_text="PostgreSQL database name to connect to.")
    schema = serializers.CharField(
        required=False,
        default="public",
        help_text="PostgreSQL schema name containing the destination table.",
    )
    table_name = serializers.CharField(
        required=False,
        default="events",
        help_text="PostgreSQL table name to write exported rows into.",
    )
    has_self_signed_cert = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Legacy SSL option for direct credential configuration. Ignored when using a PostgreSQL integration.",
    )


LEGACY_PARQUET_EXTENSION_HELP_TEXT = (
    "Whether Parquet files keep the compression codec in their extension, for example "
    "'.parquet.zst' rather than '.parquet'. Parquet records its codec inside the file, so new "
    "exports leave it out. An export that already wrote Parquet files before this setting existed "
    "keeps it, so that pipelines matching on the old names do not break. Has no effect on JSON "
    "Lines, which always carries the codec in its extension."
)


class AzureBlobDestinationConfigSerializer(serializers.Serializer):
    """Typed configuration for an Azure Blob Storage batch-export destination.

    Credentials live in the linked Integration, not in this config. Mirrors
    `AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.
    """

    container_name = serializers.CharField(help_text="Azure Blob Storage container name.")
    prefix = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Object key prefix applied to every exported file.",
    )
    compression = serializers.ChoiceField(
        choices=sorted({codec for codecs in AZURE_BLOB_SUPPORTED_COMPRESSIONS.values() for codec in codecs}),
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional compression codec applied to exported files. Valid codecs depend on file_format.",
    )
    file_format = serializers.ChoiceField(
        choices=["JSONLines", "Parquet"],
        required=False,
        default="JSONLines",
        help_text="File format used for exported objects.",
    )
    max_file_size_mb = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="If set, rolls to a new file once the current file exceeds this size in MB.",
    )

    legacy_parquet_extension = serializers.BooleanField(
        required=False,
        help_text=LEGACY_PARQUET_EXTENSION_HELP_TEXT,
    )


class S3FamilyDestinationConfigSerializer(serializers.Serializer):
    """Shared non-credential configuration for S3-family batch-export destinations.

    Credentials (and, for S3-compatible providers, the `endpoint_url`) live in the linked
    Integration, not in this config. Mirrors the non-credential fields of `S3FamilyBaseInputs` in
    `products/batch_exports/backend/service.py`.
    """

    bucket_name = serializers.CharField(help_text="Name of the destination bucket.")
    region = serializers.CharField(help_text="Region the bucket is in (e.g. 'us-east-1').")
    prefix = serializers.CharField(help_text="Object key prefix applied to every exported file.")
    compression = serializers.ChoiceField(
        choices=sorted({codec for codecs in S3_SUPPORTED_COMPRESSIONS.values() for codec in codecs}),
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional compression codec applied to exported files. Valid codecs depend on file_format.",
    )
    file_format = serializers.ChoiceField(
        choices=list(S3_SUPPORTED_COMPRESSIONS.keys()),
        required=False,
        default="JSONLines",
        help_text="File format used for exported objects.",
    )
    max_file_size_mb = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="If set, rolls to a new file once the current file exceeds this size in MB.",
    )

    legacy_parquet_extension = serializers.BooleanField(
        required=False,
        help_text=LEGACY_PARQUET_EXTENSION_HELP_TEXT,
    )


class AwsS3DestinationConfigSerializer(S3FamilyDestinationConfigSerializer):
    """Typed configuration for an AWS S3 batch-export destination.

    AWS credentials live in the linked aws-s3 Integration. Mirrors the non-credential fields of
    `AwsS3BatchExportInputs` in `products/batch_exports/backend/service.py`.
    """

    encryption = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional S3 server-side encryption algorithm (e.g. 'AES256' or 'aws:kms').",
    )
    kms_key_id = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="KMS key ID to use when encryption is 'aws:kms'.",
    )


class S3CompatibleDestinationConfigSerializer(S3FamilyDestinationConfigSerializer):
    """Typed configuration for an S3-compatible batch-export destination (Cloudflare R2,
    DigitalOcean Spaces, etc.).

    Credentials and the provider `endpoint_url` live in the linked s3-compatible Integration.
    Mirrors the non-credential fields of `S3CompatibleBatchExportInputs` in
    `products/batch_exports/backend/service.py`.
    """

    use_virtual_style_addressing = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Use virtual-hosted-style addressing rather than path-style.",
    )


class SnowflakeDestinationConfigSerializer(serializers.Serializer):
    """Typed configuration for a Snowflake batch-export destination.

    Account, user, authentication type and credentials live in the linked Integration, never here.
    Mirrors the non-credential fields of `SnowflakeBatchExportInputs` in
    `products/batch_exports/backend/service.py`.
    """

    database = serializers.CharField(help_text="Snowflake database to write to.")
    warehouse = serializers.CharField(help_text="Snowflake compute warehouse to use.")
    schema = serializers.CharField(help_text="Schema inside the database containing the destination table.")
    table_name = serializers.CharField(
        required=False,
        default="events",
        help_text="Destination table name.",
    )
    role = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional Snowflake role to assume for the session.",
    )


_AWS_CREDENTIALS_SCHEMA = {
    "type": "object",
    "properties": {
        "aws_access_key_id": {"type": "string"},
        "aws_secret_access_key": {"type": "string"},
    },
    "required": ["aws_access_key_id", "aws_secret_access_key"],
}


@extend_schema_field(
    {
        "oneOf": [
            {"type": "integer", "description": "ID of an aws-s3-kind Integration."},
            _AWS_CREDENTIALS_SCHEMA,
        ],
    }
)
class RedshiftCopyBucketCredentialsField(serializers.JSONField):
    """Inline AWS credentials or the id of an aws-s3-kind Integration."""

    pass


@extend_schema_field(
    {
        "oneOf": [
            {"type": "integer", "description": "ID of an aws-s3-kind Integration."},
            {"type": "string", "description": "ARN of an IAM role attached to the Redshift cluster."},
            _AWS_CREDENTIALS_SCHEMA,
        ],
    }
)
class RedshiftCopyAuthorizationField(serializers.JSONField):
    """IAM role ARN, inline AWS credentials, or the id of an aws-s3-kind Integration."""

    pass


class RedshiftCopyInputsSerializer(serializers.Serializer):
    """S3 staging configuration for a Redshift batch export running in COPY mode."""

    s3_bucket = serializers.CharField(help_text="S3 bucket where files are staged before the Redshift COPY.")
    region_name = serializers.CharField(help_text="AWS region of the staging S3 bucket.")
    s3_key_prefix = serializers.CharField(help_text="Key prefix for staged files in the S3 bucket.")
    authorization = RedshiftCopyAuthorizationField(
        help_text=(
            "Authorization for Redshift to read staged files during COPY: the ARN of an IAM role attached "
            "to the cluster, inline AWS credentials, or the id of an aws-s3-kind Integration."
        ),
    )
    bucket_credentials = RedshiftCopyBucketCredentialsField(
        help_text=(
            "Credentials used to stage files in the S3 bucket: inline AWS credentials or the id of an "
            "aws-s3-kind Integration."
        ),
    )


class RedshiftExportMode(models.TextChoices):
    INSERT = "INSERT", "INSERT"
    COPY = "COPY", "COPY"


class RedshiftDestinationConfigSerializer(serializers.Serializer):
    """Typed configuration for a Redshift batch-export destination.

    Connection credentials may live in a linked Integration (when one is provided) or inline in
    this config (legacy). Mirrors the non-credential fields of `RedshiftBatchExportInputs` in
    `products/batch_exports/backend/service.py`.
    """

    database = serializers.CharField(help_text="Redshift database name to connect to.")
    host = serializers.CharField(
        required=False,
        help_text=(
            "Redshift cluster or Serverless workgroup endpoint. Required when using an AWS Redshift "
            "integration; plain Redshift integrations store the host themselves."
        ),
    )
    schema = serializers.CharField(
        required=False,
        default="public",
        help_text="Redshift schema name containing the destination table.",
    )
    table_name = serializers.CharField(
        required=False,
        default="events",
        help_text="Redshift table name to write exported rows into.",
    )
    port = serializers.IntegerField(
        required=False,
        default=5439,
        help_text="Port the Redshift server listens on.",
    )
    properties_data_type = serializers.ChoiceField(
        choices=["varchar", "super"],
        required=False,
        default="varchar",
        help_text="Data type used for JSON-like columns such as event properties.",
    )
    mode = serializers.ChoiceField(
        choices=RedshiftExportMode.choices,
        required=False,
        default="INSERT",
        help_text="How rows reach Redshift: batched INSERT statements, or COPY from files staged in S3.",
    )
    copy_inputs = RedshiftCopyInputsSerializer(
        required=False,
        help_text="S3 staging configuration, required when mode is 'COPY'.",
    )


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="BatchExportDestinationConfig",
        serializers={
            "Databricks": DatabricksDestinationConfigSerializer,
            "AzureBlob": AzureBlobDestinationConfigSerializer,
            "BigQuery": BigQueryDestinationConfigSerializer,
            "Postgres": PostgresDestinationConfigSerializer,
            "AwsS3": AwsS3DestinationConfigSerializer,
            "S3Compatible": S3CompatibleDestinationConfigSerializer,
            "Snowflake": SnowflakeDestinationConfigSerializer,
            "Redshift": RedshiftDestinationConfigSerializer,
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


# Request schemas per destination type. These shape the OpenAPI spec for create/update
# request bodies so that integration-backed destinations advertise integration_id as
# required. Runtime validation still flows through BatchExportDestinationSerializer and
# its validate_destination hook — these classes are schema-only.
class DatabricksDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating a Databricks batch-export destination."""

    type = serializers.ChoiceField(choices=["Databricks"])
    integration_id = serializers.IntegerField(
        help_text="ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.",
    )
    config = DatabricksDestinationConfigSerializer()


class AzureBlobDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating an Azure Blob Storage batch-export destination."""

    type = serializers.ChoiceField(choices=["AzureBlob"])
    integration_id = serializers.IntegerField(
        help_text="ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.",
    )
    config = AzureBlobDestinationConfigSerializer()


class BigQueryDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating a BigQuery batch-export destination."""

    type = serializers.ChoiceField(choices=["BigQuery"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of a google-cloud-service-account-kind Integration. Use the integrations-list MCP tool to find one."
        ),
    )
    config = BigQueryDestinationConfigSerializer()


class PostgresDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating a PostgreSQL batch-export destination."""

    type = serializers.ChoiceField(choices=["Postgres"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of a postgresql-kind Integration providing connection credentials. Required when creating "
            "a batch export. Use the integrations-list MCP tool to find one."
        ),
    )
    config = PostgresDestinationConfigSerializer()


class AwsS3DestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating an AWS S3 batch-export destination."""

    type = serializers.ChoiceField(choices=["AwsS3"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of an aws-s3-kind Integration providing AWS credentials. "
            "Use the integrations-list MCP tool to find one."
        ),
    )
    config = AwsS3DestinationConfigSerializer()


class S3CompatibleDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating an S3-compatible batch-export destination."""

    type = serializers.ChoiceField(choices=["S3Compatible"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of an s3-compatible-kind Integration providing credentials and the provider endpoint URL. "
            "Use the integrations-list MCP tool to find one."
        ),
    )
    config = S3CompatibleDestinationConfigSerializer()


class SnowflakeDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating a Snowflake batch-export destination."""

    type = serializers.ChoiceField(choices=["Snowflake"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of a snowflake-kind Integration providing the account, user and credentials. "
            "Use the integrations-list MCP tool to find one."
        ),
    )
    config = SnowflakeDestinationConfigSerializer()


class RedshiftDestinationRequestSerializer(serializers.Serializer):
    """Request shape for creating or updating a Redshift batch-export destination."""

    type = serializers.ChoiceField(choices=["Redshift"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of an aws-redshift-kind Integration providing connection credentials. Use the "
            "integrations-list MCP tool to find one."
        ),
    )
    config = RedshiftDestinationConfigSerializer()


BatchExportDestinationRequest = PolymorphicProxySerializer(
    component_name="BatchExportDestinationRequest",
    serializers={
        "Databricks": DatabricksDestinationRequestSerializer,
        "AzureBlob": AzureBlobDestinationRequestSerializer,
        "BigQuery": BigQueryDestinationRequestSerializer,
        "Postgres": PostgresDestinationRequestSerializer,
        "AwsS3": AwsS3DestinationRequestSerializer,
        "S3Compatible": S3CompatibleDestinationRequestSerializer,
        "Snowflake": SnowflakeDestinationRequestSerializer,
        "Redshift": RedshiftDestinationRequestSerializer,
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
    `BatchExportDestinationSerializer.validate_destination`.
    """

    pass


class BatchExportDestinationSerializer(serializers.Serializer):
    """Serializer for an BatchExportDestination model.

    The `config` field is polymorphic and typed only for destinations that keep
    credentials in the linked Integration (currently Databricks, AzureBlob, BigQuery, Postgres,
    AwsS3, S3Compatible, Snowflake, Redshift). Other destination types accept the same JSON shape
    but without a typed OpenAPI schema. Secret fields are stripped from `config` on read.
    """

    type = serializers.ChoiceField(
        choices=BatchExportDestinationType.choices, help_text="A choice of supported BatchExportDestination types."
    )
    config = TypedBatchExportDestinationConfigField(
        help_text=(
            "Destination-specific configuration. Fields depend on `type`. Credentials for "
            "integration-backed destinations (Databricks, AzureBlob, BigQuery, Postgres, AwsS3, S3Compatible, "
            "Snowflake, Redshift) are NOT stored here — they live in the linked Integration. Secret fields are "
            "stripped from responses."
        ),
    )
    integration = IntegrationReferenceField(
        kinds=BATCH_EXPORT_INTEGRATION_KINDS,
        required=False,
        allow_null=True,
        help_text="The integration for this destination.",
    )
    integration_id = IntegrationReferenceField(
        kinds=BATCH_EXPORT_INTEGRATION_KINDS,
        write_only=True,
        source="integration",
        required=False,
        allow_null=True,
        help_text=(
            "ID of a team-scoped Integration providing credentials, for destinations that authenticate "
            "through one. Required for all of them."
        ),
    )

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Check the config against the destination's workflow inputs, through the facade."""
        request = self.context.get("request")
        is_patch = request is not None and request.method == "PATCH"
        # A connection test of a saved export may leave out fields, because its stored config fills them.
        # TODO: remove this and the context key that `run_test_step` sets once inline credentials are gone.
        partial = is_patch or self.context.get("partial_destination_config", False)

        try:
            attrs["config"] = batch_exports_api.validate_destination_config(
                attrs["type"], attrs["config"], partial=partial
            )
        except InvalidDestinationConfigError as e:
            raise serializers.ValidationError(str(e))

        return attrs
