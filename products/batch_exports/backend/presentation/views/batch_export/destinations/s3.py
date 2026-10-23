"""S3-family destination configuration and request serializers."""

import typing

from rest_framework import serializers

from posthog.models.integration import Integration

from products.batch_exports.backend.facade.enums import BatchExportDestinationType
from products.batch_exports.backend.temporal.destinations.constants import S3_SUPPORTED_COMPRESSIONS

from . import parquet, validation


class S3FamilyDestinationConfigSerializer(serializers.Serializer):
    """Shared non-credential configuration for S3-family batch-export destinations.

    Credentials (and, for S3-compatible providers, the `endpoint_url`) live in the linked
    Integration, not in this config. Mirrors the non-credential fields of `S3FamilyBaseInputs` in
    `products/batch_exports/backend/service.py`.
    """

    bucket_name = serializers.CharField(help_text="Name of the destination bucket.")
    region = serializers.CharField(help_text="Region the bucket is in (e.g. 'us-east-1').")
    prefix = serializers.CharField(help_text="Object key prefix applied to every exported file.")
    # nosemgrep: choices-need-a-class -- Workflow-derived choices must retain their public OpenAPI enum name.
    compression = serializers.ChoiceField(
        choices=sorted({codec for codecs in S3_SUPPORTED_COMPRESSIONS.values() for codec in codecs}),
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional compression codec applied to exported files. Valid codecs depend on file_format.",
    )
    # nosemgrep: choices-need-a-class -- Workflow-derived choices must retain their public OpenAPI enum name.
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
        help_text=parquet.LEGACY_PARQUET_EXTENSION_HELP_TEXT,
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


class S3FamilyDestinationRequestSerializer(validation.DestinationValidationSerializer):
    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        destination_type = attrs["type"]
        config = attrs["config"]
        integration = self.get_retained_integration(attrs)
        if integration is None:
            raise serializers.ValidationError(f"Integration is required for {destination_type} batch exports")

        # Credentials and the provider endpoint are not declared on the input dataclasses, so
        # `BatchExportDestinationSerializer.validate` already rejects them as unknown fields.

        # we already validate the required inputs in BatchExportDestinationSerializer::validate
        # so here we just ensure that the inputs are not empty
        required_non_empty_inputs = ["bucket_name", "region", "prefix"]
        empty_inputs = []
        for required_input in required_non_empty_inputs:
            value = config.get(required_input)
            if value is not None and isinstance(value, str) and value.strip() == "":
                empty_inputs.append(required_input)

        if empty_inputs:
            raise serializers.ValidationError(f"The following inputs are empty: {empty_inputs}")

        # The integration must match the destination kind. (Team ownership is already enforced
        # by the team-scoped `integration` field, which can only resolve integrations belonging
        # to the request's team.)
        if integration.kind != S3_DESTINATION_TO_INTEGRATION_KIND[destination_type]:
            raise serializers.ValidationError(
                f"Integration provided is not an AWS S3 integration (got kind='{integration.kind}')"
            )

        # JSONLines is the default file format for S3 exports for legacy reasons
        validation.validate_file_format(self.get_merged_config(attrs), S3_SUPPORTED_COMPRESSIONS)
        return attrs


class AwsS3DestinationRequestSerializer(S3FamilyDestinationRequestSerializer):
    """Request shape for creating or updating an AWS S3 batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["AwsS3"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of an aws-s3-kind Integration providing AWS credentials. "
            "Use the integrations-list MCP tool to find one."
        ),
    )
    config = AwsS3DestinationConfigSerializer()


class S3CompatibleDestinationRequestSerializer(S3FamilyDestinationRequestSerializer):
    """Request shape for creating or updating an S3-compatible batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["S3Compatible"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of an s3-compatible-kind Integration providing credentials and the provider endpoint URL. "
            "Use the integrations-list MCP tool to find one."
        ),
    )
    config = S3CompatibleDestinationConfigSerializer()


# S3-family destinations that may authenticate via an Integration, mapped to
# the linked integration's kind. Adding a future S3-family destination (e.g. a
# first-class GCS-via-S3 type) is a one-line addition here.
S3_DESTINATION_TO_INTEGRATION_KIND: dict[str, Integration.IntegrationKind] = {
    BatchExportDestinationType.AWS_S3: Integration.IntegrationKind.AWS_S3,
    BatchExportDestinationType.S3_COMPATIBLE: Integration.IntegrationKind.S3_COMPATIBLE,
}
