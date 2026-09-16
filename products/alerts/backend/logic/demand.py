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


def discover_synthetic_demand(cutoff: str) -> AlertDemand:
    cutoff_time = dt.datetime.fromisoformat(cutoff)
    if cutoff_time.utcoffset() is None:
        raise ValueError("Demand discovery cutoff must include a timezone")

    configuration_ids_by_source: dict[SourceKind, list[str]] = {}
    for configuration in _synthetic_configurations(cutoff_time):
        if configuration.enabled and configuration.next_check_at <= cutoff_time:
            configuration_ids_by_source.setdefault(configuration.source_kind, []).append(configuration.id)
    return AlertDemand(configuration_ids_by_source=configuration_ids_by_source)
