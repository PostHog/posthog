import datetime as dt

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import AlertDemand, SourceKind


@frozen
class _SyntheticConfiguration:
    id: str
    source_kind: SourceKind
    next_check_at: dt.datetime
    enabled: bool = True


def _synthetic_configurations(cutoff: dt.datetime) -> tuple[_SyntheticConfiguration, ...]:
    return (
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000001",
            source_kind=SourceKind.LOGS,
            next_check_at=cutoff - dt.timedelta(minutes=1),
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000002",
            source_kind=SourceKind.LOGS,
            next_check_at=cutoff,
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000003",
            source_kind=SourceKind.INSIGHT,
            next_check_at=cutoff,
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000004",
            source_kind=SourceKind.INSIGHT,
            next_check_at=cutoff + dt.timedelta(minutes=1),
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000005",
            source_kind=SourceKind.LOGS,
            next_check_at=cutoff - dt.timedelta(minutes=1),
            enabled=False,
        ),
    )


# IDs per source in one manifest. A UUID is about 40 bytes in JSON, so this keeps each source near 40 KB,
# well under the repository's 256 KB rule for Temporal payload fields. Work left out is due again next tick.
DISCOVERY_LIMIT_PER_SOURCE = 1000


def discover_synthetic_demand(cutoff: str, limit_per_source: int = DISCOVERY_LIMIT_PER_SOURCE) -> AlertDemand:
    cutoff_time = dt.datetime.fromisoformat(cutoff)
    if cutoff_time.utcoffset() is None:
        raise ValueError("Demand discovery cutoff must include a timezone")
    if limit_per_source < 1:
        raise ValueError("Demand discovery limit must be at least 1")

    configuration_ids_by_source: dict[SourceKind, list[str]] = {}
    omitted_by_source: dict[SourceKind, int] = {}
    for configuration in _synthetic_configurations(cutoff_time):
        if not configuration.enabled or configuration.next_check_at > cutoff_time:
            continue
        ids = configuration_ids_by_source.setdefault(configuration.source_kind, [])
        if len(ids) < limit_per_source:
            ids.append(configuration.id)
        else:
            omitted_by_source[configuration.source_kind] = omitted_by_source.get(configuration.source_kind, 0) + 1
    return AlertDemand(configuration_ids_by_source=configuration_ids_by_source, omitted_by_source=omitted_by_source)
