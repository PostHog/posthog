import typing
from typing import TYPE_CHECKING

from rest_framework import serializers

from posthog.models.integration import Integration
from posthog.security.url_validation import (
    INVALID_HOST_MESSAGE,
    UNREACHABLE_HOST_MESSAGE,
    ShapeError,
    validate_external_host,
)

if TYPE_CHECKING:
    from products.batch_exports.backend.models.batch_export import BatchExportDestination

from . import parquet


def recursive_dict_merge(
    old: dict[str, typing.Any],
    new: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Merge two dictionaries, and recursively merge any dictionaries in them."""
    merged = {**old, **new}

    for key, value in merged.items():
        if not isinstance(value, dict):
            continue

        # Recurse only when both sides are dicts: a dict replacing a scalar (e.g. inline
        # credentials replacing an IAM role or an integration id) is an overwrite, not a merge.
        old_value = old.get(key)
        new_value = new.get(key)
        merged[key] = recursive_dict_merge(
            old_value if isinstance(old_value, dict) else {},
            new_value if isinstance(new_value, dict) else {},
        )

    return merged


def validate_file_format(config: dict[str, typing.Any], supported_compressions: dict[str, list[str]]) -> None:
    file_format = config.get("file_format", "JSONLines")
    supported_file_formats = supported_compressions.keys()
    if file_format not in supported_file_formats:
        raise serializers.ValidationError(
            f"File format {file_format} is not supported. Supported file formats are {list(supported_file_formats)}"
        )
    compression = config.get("compression", None)
    if compression and compression not in supported_compressions[file_format]:
        raise serializers.ValidationError(
            f"Compression {compression} is not supported for file format {file_format}. Supported compressions are {supported_compressions[file_format]}"
        )


class DestinationValidationSerializer(serializers.Serializer):
    """Validate attributes already parsed by BatchExportDestinationSerializer.

    Subclass fields describe the OpenAPI request. Runtime callers use `validate`
    directly so those fields cannot insert defaults or discard legacy config fields.
    The instance is the existing destination, including for connection-test actions.
    """

    instance: "BatchExportDestination | None"

    @property
    def existing_config(self) -> dict[str, typing.Any]:
        return self.instance.config if self.instance is not None else {}

    def get_merged_config(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return recursive_dict_merge(self.existing_config, attrs["config"])

    def get_retained_integration(self, attrs: dict[str, typing.Any]) -> Integration | None:
        integration: Integration | None = attrs.get("integration")
        if integration is None and "integration" not in attrs and self.instance is not None:
            # A PATCH may send config alone, which keeps the export's existing integration.
            # An explicit `integration: null` is a removal, not an omitted field.
            integration = self.instance.integration
        return integration

    def validate_host(self, attrs: dict[str, typing.Any]) -> None:
        # PostgreSQL-server integrations (Postgres, plain Redshift) keep the host in the
        # linked Integration; AWS Redshift integrations and inline configs keep it in
        # `config`. Prefer the Integration's host when it has one so we don't skip
        # SSRF validation (and don't `KeyError` on a `config` that has no `host`).
        integration = attrs.get("integration")
        host = integration.config.get("host") if integration is not None else None
        if host is None:
            host = self.get_merged_config(attrs).get("host")

        if host is not None:
            try:
                validate_external_host(host)
            except ShapeError:
                raise serializers.ValidationError(INVALID_HOST_MESSAGE)
            except ValueError:
                raise serializers.ValidationError(UNREACHABLE_HOST_MESSAGE)

    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        destination_type = attrs["type"]
        config = attrs["config"]

        if self.instance is not None and destination_type != self.instance.type:
            raise serializers.ValidationError(
                f"Cannot change destination type from '{self.instance.type}' to '{destination_type}'. "
                "Delete this batch export and create a new one with the new destination type."
            )

        # This setting is used for grandfathered exports that used the legacy Parquet file extension,
        # and is a one-way migration; once exports use the new `.parquet` extension it is not
        # possible to go back to using the legacy extension.
        if config.get("legacy_parquet_extension") is True and not parquet._uses_legacy_parquet_extension(
            destination_type, self.existing_config
        ):
            raise serializers.ValidationError(
                "'legacy_parquet_extension' can only stay on for an export that already writes the "
                "compression codec into its Parquet file names. It cannot be turned on for a new "
                "export, or turned back on once an export moved to the standard '.parquet' extension."
            )

        return attrs
