"""Each source kind's schema for `source_config`, which the source supplies.

The platform imports no source, so a source registers a loader here when Django starts, the way it
registers its describer. A loader rather than the schema, because `ready()` runs in every process
and a schema is built on `posthog.schema`, which most processes never need.

A source registers one per alert kind it supports, because a threshold alert and an appearance alert
on the same source store different settings and are created in different ways.
"""

from products.alerts_platform.backend.facade.contracts import SourceConfigLoader, SourceConfigSpec, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertKind

_Key = tuple[SourceKind, PlatformAlertKind]

_loaders: dict[_Key, SourceConfigLoader] = {}
_specs: dict[_Key, SourceConfigSpec] = {}


def register(
    source: SourceKind, loader: SourceConfigLoader, alert_kind: PlatformAlertKind = PlatformAlertKind.THRESHOLD
) -> None:
    # One owner per source and kind. A second registrant would silently change what another product accepts.
    registered = _loaders.get((source, alert_kind))
    if registered is not None and registered is not loader:
        raise RuntimeError(f"A different source config loader is already registered for {source} {alert_kind} alerts.")
    _loaders[(source, alert_kind)] = loader


def _loaded(key: _Key, loader: SourceConfigLoader) -> SourceConfigSpec:
    if key not in _specs:
        _specs[key] = loader()
    return _specs[key]


def spec(
    source: SourceKind, alert_kind: PlatformAlertKind | str = PlatformAlertKind.THRESHOLD
) -> SourceConfigSpec | None:
    """The source's schema and rules for one alert kind, or None when the source registered none."""
    key = (source, PlatformAlertKind(alert_kind))
    loader = _loaders.get(key)
    return None if loader is None else _loaded(key, loader)


def specs(alert_kind: PlatformAlertKind = PlatformAlertKind.THRESHOLD) -> dict[SourceKind, SourceConfigSpec]:
    """Every registered source's schema for one alert kind, in a stable order so the published schema does not reorder."""
    sources = sorted((source for source, kind in _loaders if kind == alert_kind), key=lambda s: s.value)
    return {source: _loaded((source, alert_kind), _loaders[(source, alert_kind)]) for source in sources}
