"""Insight alerts on the alerts platform, for this product's own API.

Apart from `api.py`, because `posthog.tasks.alerts.utils` imports `api.py`, and the platform
modules here import `posthog.tasks.alerts.utils`.
"""

import uuid

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_alert_backfill import follow_insight_alert as follow_alert
from products.alerts.backend.platform_alert_reads import (
    moved_alert_check_page,
    moved_alert_fired_checks,
    moved_alert_statuses,
)
from products.alerts.backend.platform_insight_alert import (
    enable_native_insight_alert,
    native_insight_alert_matches,
    native_insight_alert_view,
    native_insight_alert_views,
)
from products.alerts.backend.platform_ownership import (
    close_moved_alert_firings,
    delete_alert_destinations_and_copy,
    hand_over_new_alert,
    platform_takes_new_alert_with,
    write_moved_alert_edit,
    write_native_alert_edit,
)
from products.alerts.backend.platform_subscribers import platform_subscriber_ids, sync_alert_subscriber_destinations


def follow_insight_alert(*, team_id: int, alert_id: uuid.UUID) -> None:
    """Copies an insight alert that was just created or turned back on to the platform, if its team
    runs insight alerts there."""
    alert = AlertConfiguration.objects.select_related("threshold").filter(team_id=team_id, id=alert_id).first()
    if alert is not None:
        follow_alert(alert)


__all__ = [
    "close_moved_alert_firings",
    "delete_alert_destinations_and_copy",
    "enable_native_insight_alert",
    "follow_insight_alert",
    "hand_over_new_alert",
    "moved_alert_check_page",
    "moved_alert_fired_checks",
    "moved_alert_statuses",
    "native_insight_alert_matches",
    "native_insight_alert_view",
    "native_insight_alert_views",
    "platform_takes_new_alert_with",
    "platform_subscriber_ids",
    "sync_alert_subscriber_destinations",
    "write_moved_alert_edit",
    "write_native_alert_edit",
]
