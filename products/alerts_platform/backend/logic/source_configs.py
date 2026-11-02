"""Each source kind's schema for `source_config`, which the source supplies.

The platform imports no source, so a source registers a loader here when Django starts, the way it
registers its describer. A loader rather than the schema, because `ready()` runs in every process
and a schema is built on `posthog.schema`, which most processes never need.
"""

from products.alerts_platform.backend.facade.contracts import SourceConfigLoader, SourceConfigSpec, SourceKind

_loaders: dict[SourceKind, SourceConfigLoader] = {}
_specs: dict[SourceKind, SourceConfigSpec] = {}


def register(source: SourceKind, loader: SourceConfigLoader) -> None:
    # One owner per source. A second registrant would silently change what another product accepts.
    registered = _loaders.get(source)
    if registered is not None and registered is not loader:
        raise RuntimeError(f"A different source config loader is already registered for {source} alerts.")
    _loaders[source] = loader


def _loaded(source: SourceKind, loader: SourceConfigLoader) -> SourceConfigSpec:
    if source not in _specs:
        _specs[source] = loader()
    return _specs[source]


def spec(source: SourceKind) -> SourceConfigSpec | None:
    """The source's schema and rules, or None when the source registered none."""
    loader = _loaders.get(source)
    return None if loader is None else _loaded(source, loader)


def specs() -> dict[SourceKind, SourceConfigSpec]:
    """Every registered kind's schema, in a stable order so the published schema does not reorder."""
    return {source: _loaded(source, _loaders[source]) for source in sorted(_loaders, key=lambda s: s.value)}
