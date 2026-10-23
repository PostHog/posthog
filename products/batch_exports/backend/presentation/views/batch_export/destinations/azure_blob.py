"""Azure Blob destination configuration and request serializers."""

import typing

from rest_framework import serializers

from posthog.models.integration import AzureBlobIntegration, AzureBlobIntegrationError, Integration

from products.batch_exports.backend.temporal.destinations.constants import AZURE_BLOB_SUPPORTED_COMPRESSIONS

from . import parquet, validation


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
    # nosemgrep: choices-need-a-class -- Workflow-derived choices must retain their public OpenAPI enum name.
    compression = serializers.ChoiceField(
        choices=sorted({codec for codecs in AZURE_BLOB_SUPPORTED_COMPRESSIONS.values() for codec in codecs}),
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional compression codec applied to exported files. Valid codecs depend on file_format.",
    )
    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name shared with S3 destinations.
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
        help_text=parquet.LEGACY_PARQUET_EXTENSION_HELP_TEXT,
    )


class AzureBlobDestinationRequestSerializer(validation.DestinationValidationSerializer):
    """Request shape for creating or updating an Azure Blob Storage batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["AzureBlob"])
    integration_id = serializers.IntegerField(
        help_text="ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.",
    )
    config = AzureBlobDestinationConfigSerializer()

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        integration = attrs.get("integration")
        if integration is None:
            raise serializers.ValidationError("Integration is required for Azure Blob batch exports")
        if integration.kind != Integration.IntegrationKind.AZURE_BLOB:
            raise serializers.ValidationError("Integration is not an Azure Blob integration.")
        try:
            AzureBlobIntegration(integration)
        except AzureBlobIntegrationError as e:
            raise serializers.ValidationError(str(e))

        validation.validate_file_format(self.get_merged_config(attrs), AZURE_BLOB_SUPPORTED_COMPRESSIONS)
        return attrs
