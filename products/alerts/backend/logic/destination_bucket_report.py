"""Every destination of a source's alerts, with the bucket each goes to at cutover."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Iterator

from products.alerts.backend.facade.contracts import BucketedDestination
from products.alerts.backend.logic.destination_eligibility import (
    bucket_for,
    classify_destinations_by_alert,
    classify_unbound_alert_destinations,
)
from products.alerts.backend.models.alert import AlertConfiguration


def bucketed_destinations(
    team_alerts: Iterable[tuple[int, str]], *, allowed_event_ids: Collection[str]
) -> Iterator[BucketedDestination]:
    """Per team, the destinations bound to no single alert, then each alert's own destinations."""
    alert_ids_by_team: dict[int, list[str]] = {}
    for team_id, alert_id in team_alerts:
        alert_ids_by_team.setdefault(team_id, []).append(alert_id)
    for team_id, alert_ids in alert_ids_by_team.items():
        unbound = classify_unbound_alert_destinations(team_id=team_id, allowed_event_ids=allowed_event_ids)
        for eligibility in unbound:
            yield BucketedDestination(team_id=team_id, alert_id=None, eligibility=eligibility)
        unbound_ids = {eligibility.hog_function_id for eligibility in unbound}
        by_alert = classify_destinations_by_alert(
            team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids
        )
        for alert_id, eligibilities in by_alert.items():
            for eligibility in eligibilities:
                # A function that excludes this alert also names its id, but it is unbound and reported once.
                if eligibility.hog_function_id not in unbound_ids:
                    yield BucketedDestination(team_id=team_id, alert_id=alert_id, eligibility=eligibility)


def enabled_insight_alerts(*, team_id: int | None = None) -> Iterator[tuple[int, str]]:
    alerts = AlertConfiguration.objects.filter(enabled=True).order_by("team_id", "created_at")
    if team_id is not None:
        alerts = alerts.filter(team_id=team_id)
    for alert_team_id, alert_id in alerts.values_list("team_id", "id").iterator():
        yield alert_team_id, str(alert_id)


def bucket_report_lines(team_alerts: Iterable[tuple[int, str]], *, allowed_event_ids: Collection[str]) -> Iterator[str]:
    """One line per destination, then the count per bucket and per reason."""
    buckets: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for destination in bucketed_destinations(team_alerts, allowed_event_ids=allowed_event_ids):
        eligibility = destination.eligibility
        bucket = bucket_for(eligibility)
        buckets[str(bucket)] += 1
        reasons.update(str(reason) for reason in eligibility.hold_backs)
        if destination.alert_id is None:
            reasons["unbound"] += 1
        yield (
            f"team={destination.team_id} alert={destination.alert_id or 'unbound'} "
            f"destination={eligibility.hog_function_id} template={eligibility.template_id} "
            f"bucket={bucket} code_hash={eligibility.code_hash} reasons={','.join(eligibility.hold_backs)}"
        )
    yield f"Destinations by bucket: {dict(buckets) or 'none'}"
    yield f"Hold-backs by reason: {dict(reasons) or 'none'}"
