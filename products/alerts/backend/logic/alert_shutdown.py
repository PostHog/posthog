"""Stopping the alerts of teams that staff shut down for abuse."""

from collections.abc import Collection

from products.alerts.backend.models.alert import AlertConfiguration


def enabled_alert_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        AlertConfiguration.objects.filter(team_id__in=team_ids, enabled=True)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(alert_id) for alert_id in rows]


def disable_alert(alert_id: str, *, team_ids: Collection[int]) -> bool:
    disabled = AlertConfiguration.objects.filter(team_id__in=team_ids, id=alert_id, enabled=True).update(enabled=False)
    return disabled > 0
