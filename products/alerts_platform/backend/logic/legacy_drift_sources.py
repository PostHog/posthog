from products.alerts_platform.backend.facade.contracts import LegacyDriftSource, SourceKind

_sources: dict[SourceKind, LegacyDriftSource] = {}


def register(source: SourceKind, provider: LegacyDriftSource) -> None:
    registered = _sources.get(source)
    if registered is not None and registered is not provider:
        raise RuntimeError(f"A different drift source is already registered for {source} alerts.")
    _sources[source] = provider


def provider_of(source: SourceKind) -> LegacyDriftSource:
    return _sources[source]


def registered_sources() -> tuple[SourceKind, ...]:
    return tuple(_sources)
