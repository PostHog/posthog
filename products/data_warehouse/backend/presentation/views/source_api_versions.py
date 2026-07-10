from typing import Any

from rest_framework import serializers

from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class ExternalDataSourceApiVersionDeprecationSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="The deprecated vendor API version this source is pinned to.")
    sunset_at = serializers.DateField(
        allow_null=True, help_text="Date the vendor stops serving this version; null if not announced."
    )
    default_version = serializers.CharField(
        help_text="The source's current default vendor API version — the migration target."
    )


def api_version_deprecation_payload(source_type: str, pinned: str | None) -> dict[str, Any] | None:
    """Wire payload for the generic API-version deprecation warning, or None when the effective
    version is not deprecated (or the source type is unknown/unregistered)."""
    try:
        source_impl = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except ValueError:
        return None
    deprecation = source_impl.get_version_deprecation(pinned)
    if deprecation is None:
        return None
    return {
        "version": deprecation.version,
        "sunset_at": deprecation.sunset_at.isoformat() if deprecation.sunset_at else None,
        "default_version": source_impl.default_version,
    }
