import datetime as dt

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import AlertBatchKey, AlertDemand, SourceKind


@frozen
class _SyntheticConfiguration:
    id: str
    source_kind: SourceKind
    team_id: int
    next_check_at: dt.datetime
    enabled: bool = True


def _synthetic_configurations(cutoff: dt.datetime) -> tuple[_SyntheticConfiguration, ...]:
    return (
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000001",
            source_kind=SourceKind.LOGS,
            team_id=1,
            next_check_at=cutoff - dt.timedelta(minutes=1),
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000002",
            source_kind=SourceKind.LOGS,
            team_id=1,
            next_check_at=cutoff,
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000003",
            source_kind=SourceKind.INSIGHT,
            team_id=2,
            next_check_at=cutoff,
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000004",
            source_kind=SourceKind.INSIGHT,
            team_id=2,
            next_check_at=cutoff + dt.timedelta(minutes=1),
        ),
        _SyntheticConfiguration(
            id="00000000-0000-4000-8000-000000000005",
            source_kind=SourceKind.LOGS,
            team_id=1,
            next_check_at=cutoff - dt.timedelta(minutes=1),
            enabled=False,
        ),
    )


# Keys per source in one manifest. A key is a team id and a minute, so unlike an id list it does not
# grow with a team's alert count, and this bound is about how many distinct chunks one tick starts.
DISCOVERY_LIMIT_PER_SOURCE = 1000


def _slot(next_check_at: dt.datetime) -> str:
    """The minute a configuration is due for. Load spreading moves alerts between minutes rather
    than within one, so flooring here loses nothing it was meant to spread."""
    return next_check_at.replace(second=0, microsecond=0).isoformat()


def discover_demand(cutoff: str, limit_per_source: int = DISCOVERY_LIMIT_PER_SOURCE) -> AlertDemand:
    cutoff_time = dt.datetime.fromisoformat(cutoff)
    if cutoff_time.utcoffset() is None:
        raise ValueError("Demand discovery cutoff must include a timezone")
    if limit_per_source < 1:
        raise ValueError("Demand discovery limit must be at least 1")

    # Oldest due first, so a key the bound leaves out grows more overdue and wins a later tick.
    # Any stable ordering that is not by due time starves the same keys every tick instead.
    due = sorted(
        (
            configuration
            for configuration in _synthetic_configurations(cutoff_time)
            if configuration.enabled and configuration.next_check_at <= cutoff_time
        ),
        key=lambda configuration: (configuration.next_check_at, configuration.id),
    )

    keys_by_source: dict[SourceKind, list[AlertBatchKey]] = {}
    seen: dict[SourceKind, set[tuple[int, str]]] = {}
    omitted_by_source: dict[SourceKind, int] = {}
    for configuration in due:
        key = AlertBatchKey(team_id=configuration.team_id, slot=_slot(configuration.next_check_at))
        source_seen = seen.setdefault(configuration.source_kind, set())
        if (key.team_id, key.slot) in source_seen:
            continue
        keys = keys_by_source.setdefault(configuration.source_kind, [])
        if len(keys) < limit_per_source:
            source_seen.add((key.team_id, key.slot))
            keys.append(key)
        else:
            omitted_by_source[configuration.source_kind] = omitted_by_source.get(configuration.source_kind, 0) + 1
    return AlertDemand(batch_keys_by_source=keys_by_source, omitted_by_source=omitted_by_source)
