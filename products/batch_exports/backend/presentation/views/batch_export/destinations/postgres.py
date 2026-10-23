"""Postgres destination configuration and request serializers."""

import typing

from rest_framework import serializers

from posthog.models.integration import Integration

from . import validation


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


class PostgresDestinationRequestSerializer(validation.DestinationValidationSerializer):
    """Request shape for creating or updating a PostgreSQL batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["Postgres"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of a postgresql-kind Integration providing connection credentials. Required when creating "
            "a batch export. Use the integrations-list MCP tool to find one."
        ),
    )
    config = PostgresDestinationConfigSerializer()

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        integration = attrs.get("integration")
        # New Postgres exports must use an Integration for credentials. Exports created before
        # integrations existed keep their inline credentials, so only require it on create
        # (`instance is None`); existing inline-credential exports stay valid when edited.
        if integration is None and self.instance is None:
            raise serializers.ValidationError("Integration is required for Postgres batch exports")
        if integration is not None and integration.kind != Integration.IntegrationKind.POSTGRESQL:
            raise serializers.ValidationError("Integration is not a PostgreSQL integration.")

        self.validate_host(attrs)
        return attrs
