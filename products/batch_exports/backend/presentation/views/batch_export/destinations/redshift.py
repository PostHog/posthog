"""Redshift destination configuration and request serializers."""

import typing

from django.db import models

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models.integration import Integration

from . import validation

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
    # nosemgrep: choices-need-a-class -- Preserve the public PropertiesDataTypeEnum OpenAPI component.
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


class RedshiftDestinationRequestSerializer(validation.DestinationValidationSerializer):
    """Request shape for creating or updating a Redshift batch-export destination."""

    # nosemgrep: choices-need-a-class -- Preserve the public OpenAPI enum name for this singleton discriminator.
    type = serializers.ChoiceField(choices=["Redshift"])
    integration_id = serializers.IntegerField(
        help_text=(
            "ID of an aws-redshift-kind Integration providing connection credentials. Use the "
            "integrations-list MCP tool to find one."
        ),
    )
    config = RedshiftDestinationConfigSerializer()

    def validate_copy_inputs(self, merged_config: dict[str, typing.Any]) -> None:
        if merged_config.get("mode") != "COPY":
            return

        copy_inputs = merged_config.get("copy_inputs", {})
        if not copy_inputs:
            raise serializers.ValidationError("Missing required inputs for 'COPY'")

        required_inputs = {"s3_bucket", "region_name", "authorization", "bucket_credentials"}
        if required_inputs - copy_inputs.keys():
            raise serializers.ValidationError("Missing required input for 'COPY'")

        credential_keys = {"aws_access_key_id", "aws_secret_access_key"}
        bucket_credentials = copy_inputs["bucket_credentials"]
        bucket_integration_id = _coerce_integration_id(bucket_credentials)
        authorization = copy_inputs.get("authorization")
        authorization_integration_id = _coerce_integration_id(authorization)

        existing_copy_inputs = self.existing_config.get("copy_inputs") or {}
        for field_name, copy_integration_id in (
            ("bucket_credentials", bucket_integration_id),
            ("authorization", authorization_integration_id),
        ):
            # Sticky like the top-level integration: COPY credentials that reference an
            # integration cannot drop back to inline values.
            # TODO: remove this guard once integrations are mandatory for Redshift and
            # inline credentials are gone.
            if (
                self.instance is not None
                and copy_integration_id is None
                and _coerce_integration_id(existing_copy_inputs.get(field_name)) is not None
            ):
                raise serializers.ValidationError(
                    f"Cannot switch '{field_name}' from an integration to inline credentials. "
                    "Send a different integration ID to swap, or omit the field to keep the current one."
                )
            if copy_integration_id is None:
                continue
            # These ids live inside `config` rather than the team-scoped `integration`
            # field, so team ownership must be checked here.
            if not Integration.objects.filter(
                id=copy_integration_id,
                team_id=self.context["team_id"],
                kind=Integration.IntegrationKind.AWS_S3,
            ).exists():
                raise serializers.ValidationError(
                    f"'{field_name}' does not reference an AWS S3 integration of this project."
                )

        if bucket_integration_id is None and (
            not isinstance(bucket_credentials, dict) or credential_keys - bucket_credentials.keys()
        ):
            raise serializers.ValidationError("Missing required bucket credentials for 'COPY'")

        if authorization_integration_id is None:
            if isinstance(authorization, dict):
                if credential_keys - authorization.keys():
                    raise serializers.ValidationError("Missing required credentials for 'COPY'")
            elif isinstance(authorization, str):
                if not authorization.strip():
                    raise serializers.ValidationError("Missing required IAM role for 'COPY'")
            else:
                raise serializers.ValidationError(
                    "Authorization for 'COPY' must be an IAM role ARN, AWS credentials, or an integration ID."
                )

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        integration = attrs.get("integration")
        merged_config = self.get_merged_config(attrs)

        # Sticky integration: an export that uses one cannot drop back to inline credentials.
        # TODO: remove this guard once inline credentials are gone.
        if self.instance is not None and self.instance.integration is not None and integration is None:
            raise serializers.ValidationError(
                "Cannot remove the integration from a Redshift batch export that uses one. "
                "Re-send its `integration` to keep it (or a different one to swap)."
            )

        # New Redshift exports must use an Integration for credentials. Exports created before
        # integrations existed keep their inline credentials, so only require it on create
        # (`instance is None`); existing inline-credential exports stay valid when edited.
        if integration is None and self.instance is None:
            raise serializers.ValidationError("Integration is required for Redshift batch exports")

        if integration is not None:
            # (Team ownership is already enforced by the team-scoped `integration` field.)
            if integration.kind != Integration.IntegrationKind.AWS_REDSHIFT:
                raise serializers.ValidationError("Integration is not a Redshift integration.")

            # Only plain Redshift integrations store a host; AWS-flavor ones obtain
            # temporary credentials for a cluster endpoint that stays in the export config.
            if "host" not in integration.config and not merged_config.get("host"):
                raise serializers.ValidationError(
                    "A 'host' is required when using an AWS Redshift integration: "
                    "set it to the cluster or workgroup endpoint."
                )

        self.validate_copy_inputs(merged_config)
        self.validate_host(attrs)
        return attrs
