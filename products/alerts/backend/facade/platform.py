"""Insight alerts on the alerts platform, for this product's own API.

Apart from `api.py`, because `posthog.tasks.alerts.utils` imports `api.py`, and the platform
modules here import `posthog.tasks.alerts.utils`.
"""

from products.alerts.backend.platform_alert_reads import (
    moved_alert_check_page,
    moved_alert_fired_checks,
    moved_alert_statuses,
)
from products.alerts.backend.platform_insight_alert import (
    delete_native_insight_alert,
    enable_native_insight_alert,
    native_insight_alert_ids_by_insight,
    native_insight_alert_matches,
    native_insight_alert_view,
    native_insight_alert_views,
    show_copy_settings,
    subscribers_with_insight_access,
)
from products.alerts.backend.platform_ownership import (
    close_moved_alert_firings,
    create_native_alert,
    creates_native_alert,
    delete_alert_destinations_and_copy,
    hand_over_new_alert,
    on_updated,
    platform_takes_new_alert_with,
    show_locked_copy,
    write_native_alert_edit,
)
from products.alerts.backend.platform_subscribers import (
    platform_subscriber_ids,
    set_native_subscribers,
    sync_alert_subscriber_destinations,
)

__all__ = [
    "close_moved_alert_firings",
    "create_native_alert",
    "creates_native_alert",
    "delete_alert_destinations_and_copy",
    "delete_native_insight_alert",
    "enable_native_insight_alert",
    "hand_over_new_alert",
    "moved_alert_check_page",
    "moved_alert_fired_checks",
    "moved_alert_statuses",
    "native_insight_alert_matches",
    "native_insight_alert_ids_by_insight",
    "native_insight_alert_view",
    "native_insight_alert_views",
    "on_updated",
    "platform_takes_new_alert_with",
    "platform_subscriber_ids",
    "set_native_subscribers",
    "show_copy_settings",
    "show_locked_copy",
    "subscribers_with_insight_access",
    "sync_alert_subscriber_destinations",
    "write_native_alert_edit",
]
