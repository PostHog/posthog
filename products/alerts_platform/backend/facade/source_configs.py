"""Facade for the schema each source kind gives its `source_config`."""

from products.alerts_platform.backend.facade.contracts import SourceConfigLoader, SourceConfigSpec, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertKind
from products.alerts_platform.backend.logic import source_configs


def register_source_config(
    source: SourceKind, loader: SourceConfigLoader, alert_kind: PlatformAlertKind = PlatformAlertKind.THRESHOLD
) -> None:
    source_configs.register(source, loader, alert_kind)


def editable_source_configs() -> dict[SourceKind, SourceConfigSpec]:
    """Every kind the API can write, with its schema. Loads each schema on first call.

    Threshold alerts only. Appearance alerts are created outside this API until it takes an alert kind.
    """
    return source_configs.specs()
