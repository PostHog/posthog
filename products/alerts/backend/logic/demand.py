import datetime as dt

from django.db.models import Q

from products.alerts.backend.facade.contracts import AlertBatchKey, AlertDemand, SourceKind
from products.alerts.backend.logic.platform_lifecycle import slot_of
from products.alerts.backend.models import PlatformAlertConfiguration

# Keys per source in one manifest. A key is a team id and a minute, so unlike an id list it does not
# grow with a team's alert count, and this bound is about how many distinct chunks one tick starts.
DISCOVERY_LIMIT_PER_SOURCE = 1000


def discover_demand(cutoff: str, limit_per_source: int = DISCOVERY_LIMIT_PER_SOURCE) -> AlertDemand:
    cutoff_time = dt.datetime.fromisoformat(cutoff)
    if cutoff_time.utcoffset() is None:
        raise ValueError("Demand discovery cutoff must include a timezone")
    if limit_per_source < 1:
        raise ValueError("Demand discovery limit must be at least 1")

    # Discovery is cross-team by definition, so it opts out of team scoping rather than running
    # once per team. Oldest due first, so a key the bound leaves out grows more overdue and wins a
    # later tick; any stable ordering that is not by due time starves the same keys every tick.
    due = (
        PlatformAlertConfiguration.objects.unscoped()
        .filter(Q(enabled=True) & (Q(next_check_at__lte=cutoff_time) | Q(next_check_at__isnull=True)))
        .order_by("next_check_at", "id")
        .values_list("source_kind", "team_id", "next_check_at")
    )

    keys_by_source: dict[SourceKind, list[AlertBatchKey]] = {}
    seen: dict[SourceKind, set[AlertBatchKey]] = {}
    omitted_by_source: dict[SourceKind, int] = {}
    for raw_source, team_id, next_check_at in due.iterator():
        source = SourceKind(raw_source)
        key = AlertBatchKey(team_id=team_id, slot=slot_of(next_check_at, cutoff_time))
        source_seen = seen.setdefault(source, set())
        if key in source_seen:
            continue
        source_seen.add(key)
        keys = keys_by_source.setdefault(source, [])
        if len(keys) < limit_per_source:
            keys.append(key)
        else:
            omitted_by_source[source] = omitted_by_source.get(source, 0) + 1
    return AlertDemand(batch_keys_by_source=keys_by_source, omitted_by_source=omitted_by_source)
