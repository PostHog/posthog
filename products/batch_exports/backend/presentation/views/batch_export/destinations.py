"""Batch export destination serializers: the typed config and request shape of each destination type."""

import typing
import builtins
import dataclasses
import collections.abc

from django.db import models

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models.integration import Integration
from posthog.utils import str_to_bool

from products.batch_exports.backend.models.batch_export import OBJECT_STORAGE_DESTINATIONS, BatchExportDestination
from products.batch_exports.backend.service import (
    DESTINATION_WORKFLOWS,
    BaseBatchExportInputs,
    coerce_config_to_declared_types,
)
from products.batch_exports.backend.temporal.destinations.constants import (
    AZURE_BLOB_SUPPORTED_COMPRESSIONS,
    S3_SUPPORTED_COMPRESSIONS,
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


# S3-family destinations that may authenticate via an Integration, mapped to
# the linked integration's kind. Adding a future S3-family destination (e.g. a
# first-class GCS-via-S3 type) is a one-line addition here.
S3_DESTINATION_TO_INTEGRATION_KIND: dict[str, Integration.IntegrationKind] = {
    BatchExportDestination.Destination.AWS_S3: Integration.IntegrationKind.AWS_S3,
    BatchExportDestination.Destination.S3_COMPATIBLE: Integration.IntegrationKind.S3_COMPATIBLE,
}


def _writes_compressed_parquet(config: dict[str, typing.Any]) -> bool:
    """Whether a config produces Parquet file names that carry a compression codec."""
    return config.get("file_format") == "Parquet" and config.get("compression") is not None


def _uses_legacy_parquet_extension(destination_type: str, stored_config: dict[str, typing.Any]) -> bool:
    """Whether an export's stored config already writes the codec into its Parquet file names.

    Reads through `coerce_config_to_declared_types`, because `EncryptedJSONField` stringifies
    scalars on write and the string "False" is truthy.
    """
    coerced = coerce_config_to_declared_types(destination_type, stored_config)
    stored = coerced.get("legacy_parquet_extension")
    if stored is None:
        # export was created before the `legacy_parquet_extension` field was added
        # so will use the legacy extension if it writes compressed Parquet files
        return _writes_compressed_parquet(coerced)
    return bool(stored)


def _set_default_parquet_extension(destination_type: str, config: dict[str, typing.Any]) -> None:
    """Opt a newly created destination into the standard `.parquet` extension.

    The workflow input dataclasses default this to `True`, so that an export whose Temporal
    schedule predates the field keeps the same file extension as before in order to maintain
    compatibility.
    """
    if destination_type in OBJECT_STORAGE_DESTINATIONS:
        config.setdefault("legacy_parquet_extension", False)


def _pin_existing_parquet_extension(destination_type: str, stored_config: dict[str, typing.Any]) -> None:
    """Record what an export's file names already look like, before a patch can change its format.

    An export that predates this setting has no value for it, and a missing value reads as the
    legacy naming. That is correct only for an export that already writes names carrying a codec,
    which means Parquet with a compression codec set. An export on JSON Lines, or on Parquet with
    no compression, has no such names to keep, so moving it to compressed Parquet has to produce
    `.parquet` rather than `.parquet.zst`.

    Takes the config as stored, before the incoming patch merges into it, so the value reflects
    what the export has been running rather than what it is moving to. An explicit value in the
    patch still wins, because the merge applies afterwards.
    """
    if destination_type not in OBJECT_STORAGE_DESTINATIONS:
        return

    stored_config.setdefault("legacy_parquet_extension", _writes_compressed_parquet(stored_config))


def _coerce_integration_id(value: typing.Any) -> int | None:
    """Return the integration id encoded in a Redshift COPY credential value, if any.

    `BatchExportDestination.config` is an `EncryptedJSONField`, which stringifies scalar
    leaves on the decrypt round trip, so an id may arrive as an int or a numeric string.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model.

    The `config` field is polymorphic and typed only for destinations that keep
    credentials in the linked Integration (currently Databricks, AzureBlob, BigQuery, Postgres,
    AwsS3, S3Compatible, Snowflake, Redshift). Other destination types accept the same JSON shape
    but without a typed OpenAPI schema. Secret fields are stripped from `config` on read.
    """

    config = TypedBatchExportDestinationConfigField(
        help_text=(
            "Destination-specific configuration. Fields depend on `type`. Credentials for "
            "integration-backed destinations (Databricks, AzureBlob, BigQuery, Postgres, AwsS3, S3Compatible, "
            "Snowflake, Redshift) are NOT stored here — they live in the linked Integration. Secret fields are "
            "stripped from responses."
        ),
    )
    integration = TeamScopedPrimaryKeyRelatedField(
        queryset=Integration.objects.all(),
        required=False,
        allow_null=True,
        help_text="The integration for this destination.",
    )
    integration_id = TeamScopedPrimaryKeyRelatedField(
        write_only=True,
        queryset=Integration.objects.all(),
        source="integration",
        required=False,
        allow_null=True,
        help_text=(
            "ID of a team-scoped Integration providing credentials, for destinations that authenticate "
            "through one. Required for all of them."
        ),
    )

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config", "integration", "integration_id"]

    def create(self, validated_data: collections.abc.Mapping[str, typing.Any]) -> BatchExportDestination:
        """Create a BatchExportDestination."""
        export_destination = BatchExportDestination.objects.create(**validated_data)
        return export_destination

    def validate(self, attrs: collections.abc.Mapping[str, typing.Any]) -> collections.abc.Mapping[str, typing.Any]:
        """Validate the destination configuration based on workflow inputs.

        Ensure that the submitted destination configuration passes the following checks:
        * Does NOT contain fields that do not exist in workflow inputs.
        * Contains all required fields as defined by workflow inputs.
        * Provided values match types required by workflow inputs.

        Raises:
            A `serializers.ValidationError` if any of these checks fail.
        """
        export_type, config = attrs["type"], attrs["config"]
        request = self.context.get("request")
        is_patch = request is not None and request.method == "PATCH"

        _, workflow_inputs = DESTINATION_WORKFLOWS[export_type]
        base_field_names = {field.name for field in dataclasses.fields(BaseBatchExportInputs)}
        workflow_fields = dataclasses.fields(workflow_inputs)
        destination_fields = {field for field in workflow_fields if field.name not in base_field_names}

        extra_fields = config.keys() - {field.name for field in destination_fields} - base_field_names
        if extra_fields:
            str_fields = ", ".join(f"'{extra_field}'" for extra_field in sorted(extra_fields))
            raise serializers.ValidationError(f"Configuration has unknown field/s: {str_fields}")

        # Destination config fields without a dataclass default must be provided.
        for destination_field in destination_fields:
            is_required = (
                destination_field.default == dataclasses.MISSING
                and destination_field.default_factory == dataclasses.MISSING
            )
            if destination_field.name not in config:
                if is_required and not is_patch:
                    # When patching we expect a partial configuration. So, we don't
                    # error on missing required fields.
                    raise serializers.ValidationError(
                        f"Configuration missing required field: '{destination_field.name}'"
                    )
                else:
                    continue

            config_value = config[destination_field.name]
            field_type = destination_field.type

            if not isinstance(field_type, type):
                # `dataclasses.Field.type` could be something we can't work with.
                # TODO: Validate these ones too?
                continue

            if not isinstance(config_value, field_type):
                config_value, success = try_convert_to_type(config_value, field_type)

                if not success:
                    raise serializers.ValidationError(
                        f"Configuration has invalid type: got '{type(config_value).__name__}', expected '{field_type.__name__}'"
                    )

                config[destination_field.name] = config_value

        return attrs

    def to_representation(self, instance: BatchExportDestination) -> dict:
        data = super().to_representation(instance)

        def remove_secret_fields_recursive(d: dict[str, typing.Any]):
            target = {}

            for k, v in d.items():
                if k in BatchExportDestination.secret_fields[instance.type]:
                    continue
                elif isinstance(v, dict):
                    target[k] = remove_secret_fields_recursive(v)
                else:
                    target[k] = v

            return target

        config = remove_secret_fields_recursive(data["config"])
        data["config"] = coerce_config_to_declared_types(instance.type, config)

        return data


Success = bool


def try_convert_to_type(value: typing.Any, target_type: type) -> tuple[typing.Any, Success]:
    """Attempt to convert value to target type based on well-known casting functions.

    This doesn't raise any exceptions but rather returns a tuple with a bool indicating
    if the value in the first position was successfully casted to `target_type` or not.
    If casting fails, the value in the first position is returned unchanged, otherwise a
    new value of type `target_type` is returned.
    """
    current_type = type(value)

    match (current_type, target_type):
        case (builtins.str, builtins.bool):
            cast_func: typing.Callable[[typing.Any], typing.Any] = str_to_bool
        case (builtins.str, builtins.int):
            cast_func = int
        case _:
            return (value, False)

    try:
        new_value = cast_func(value)
    except Exception:
        return (value, False)

    return (new_value, True)
