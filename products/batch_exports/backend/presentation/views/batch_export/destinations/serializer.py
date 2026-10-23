"""Destination model serialization and workflow-input validation."""

import typing
import builtins
import dataclasses
import collections.abc

from rest_framework import serializers

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models.integration import Integration
from posthog.utils import str_to_bool

from products.batch_exports.backend.models.batch_export import BatchExportDestination
from products.batch_exports.backend.service import (
    DESTINATION_WORKFLOWS,
    BaseBatchExportInputs,
    coerce_config_to_declared_types,
)

from . import schema


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model.

    The `config` field is polymorphic and typed only for destinations that keep
    credentials in the linked Integration (currently Databricks, AzureBlob, BigQuery, Postgres,
    AwsS3, S3Compatible, Snowflake, Redshift). Other destination types accept the same JSON shape
    but without a typed OpenAPI schema. Secret fields are stripped from `config` on read.
    """

    config = schema.TypedBatchExportDestinationConfigField(
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
