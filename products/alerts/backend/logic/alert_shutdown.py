"""Stopping the insight alerts of teams that staff shut down for abuse."""

from collections.abc import Collection

from django.db import transaction

from products.alerts.backend.insight_alert_state_machine import apply_disable
from products.alerts.backend.models.alert import AlertConfiguration


def enabled_alert_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        AlertConfiguration.objects.filter(team_id__in=team_ids, enabled=True)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(alert_id) for alert_id in rows]


def disable_alert(alert_id: str, *, team_id: int) -> bool:
    with transaction.atomic():
        # The insight row is locked before the platform's copy, as every writer of both rows does.
        alert = (
            AlertConfiguration.objects.select_for_update().filter(team_id=team_id, id=alert_id, enabled=True).first()
        )
        if alert is None:
            return False
        alert.save(update_fields=apply_disable(alert))
        if alert.platform_owned:
            # The platform's copy is what its scheduler checks, so it has to switch off with the insight row.
            # Deferred: platform_ownership imports the alerts facade, which imports this module.
            from products.alerts.backend.platform_ownership import on_updated  # noqa: PLC0415

            on_updated(alert, snooze_changed=False)
    return True
