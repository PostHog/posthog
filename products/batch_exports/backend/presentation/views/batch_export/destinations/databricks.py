"""Databricks destination configuration and request serializers."""

import typing

from rest_framework import serializers

from posthog.models.integration import DatabricksIntegration, DatabricksIntegrationError, Integration

from . import validation


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


class DatabricksDestinationRequestSerializer(validation.DestinationValidationSerializer):
    """Request shape for creating or updating a Databricks batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["Databricks"])
    integration_id = serializers.IntegerField(
        help_text="ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.",
    )
    config = DatabricksDestinationConfigSerializer()

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        integration = attrs.get("integration")
        if integration is None:
            raise serializers.ValidationError("Integration is required for Databricks batch exports")
        if integration.kind != Integration.IntegrationKind.DATABRICKS:
            raise serializers.ValidationError("Integration is not a Databricks integration.")
        try:
            DatabricksIntegration(integration)
        except DatabricksIntegrationError as e:
            raise serializers.ValidationError(str(e))
        return attrs
