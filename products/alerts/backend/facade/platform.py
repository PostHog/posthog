"""Insight alerts on the alerts platform, for this product's own API.

Apart from `api.py`, because `posthog.tasks.alerts.utils` imports `api.py`, and the platform
modules here import `posthog.tasks.alerts.utils`.
"""

import uuid

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_alert_backfill import follow_insight_alert as follow_alert
from products.alerts.backend.platform_alert_reads import moved_alert_check_page, moved_alert_statuses
from products.alerts.backend.platform_ownership import (
    close_moved_alert_firings,
    delete_moved_alert_copy,
    hand_over_new_alert,
    write_moved_alert_edit,
)


def follow_insight_alert(*, team_id: int, alert_id: uuid.UUID) -> None:
    """Copies an insight alert that was just created or turned back on to the platform, if its team
    runs insight alerts there."""
    alert = AlertConfiguration.objects.select_related("threshold").filter(team_id=team_id, id=alert_id).first()
    if alert is not None:
        follow_alert(alert)


__all__ = [
    "close_moved_alert_firings",
    "delete_moved_alert_copy",
    "follow_insight_alert",
    "hand_over_new_alert",
    "moved_alert_check_page",
    "moved_alert_statuses",
    "write_moved_alert_edit",
]
