"""Snowflake destination configuration and request serializers."""

import typing

from rest_framework import serializers

from posthog.models.integration import SnowflakeIntegration, SnowflakeIntegrationError

from . import validation


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


class SnowflakeDestinationRequestSerializer(validation.DestinationValidationSerializer):
    """Request shape for creating or updating a Snowflake batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["Snowflake"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of a snowflake-kind Integration providing the account, user and credentials. "
            "Use the integrations-list MCP tool to find one."
        ),
    )
    config = SnowflakeDestinationConfigSerializer()

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        integration = self.get_retained_integration(attrs)
        if integration is None:
            raise serializers.ValidationError("Integration is required for Snowflake batch exports")

        # Also rejects an integration missing its account, user or authentication type, so a
        # half-built one fails here rather than on the export's first run.
        try:
            SnowflakeIntegration(integration)
        except SnowflakeIntegrationError as e:
            raise serializers.ValidationError(str(e))

        return attrs
