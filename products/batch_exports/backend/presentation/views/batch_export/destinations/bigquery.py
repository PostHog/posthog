"""BigQuery destination configuration and request serializers."""

import typing

from rest_framework import serializers

from posthog.models.integration import Integration

from . import validation


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


class BigQueryDestinationRequestSerializer(validation.DestinationValidationSerializer):
    """Request shape for creating or updating a BigQuery batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["BigQuery"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of a google-cloud-service-account-kind Integration. Use the integrations-list MCP tool to find one."
        ),
    )
    config = BigQueryDestinationConfigSerializer()

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        integration = attrs.get("integration")
        if integration is None:
            raise serializers.ValidationError("Integration is required for BigQuery batch exports")
        if integration.kind != Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT:
            raise serializers.ValidationError("Integration is not a Google Cloud service account integration.")
        return attrs
