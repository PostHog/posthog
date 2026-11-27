"""
Dashboard access classification and cache telemetry.

Insights render inside dashboards, so the insight API classifies how a render was reached and
records the cache outcome under the dashboards metrics. It imports both from here rather than
reaching the internal ``access`` module. The dashboard and sharing views record their reads here too.
"""

from datetime import datetime

from products.dashboards.backend import access
from products.dashboards.backend.access import (
    dashboard_access_method,
    record_dashboard_access,
    record_dashboard_cache_outcome,
)
from products.dashboards.backend.facade.enums import DashboardAccessMethod
from products.dashboards.backend.models.dashboard import Dashboard


def record_dashboard_view(*, dashboard_id: int, access_method: DashboardAccessMethod) -> datetime | None:
    """Stamp a dashboard as opened now, count the access under how it was reached, and return the stamp.

    Saves the row, so its save signals run. A soft-deleted dashboard is stamped too, and an id that
    matches no dashboard records nothing and returns None. Unscoped: the caller resolved the id from its own row.
    """
    # nosemgrep: idor-lookup-without-team (the caller resolved the id from one of its own team's rows)
    dashboard = Dashboard.objects_including_soft_deleted.filter(pk=dashboard_id).first()
    if dashboard is None:
        return None
    access.record_dashboard_view(dashboard, access_method)
    return dashboard.last_accessed_at


__all__ = [
    "DashboardAccessMethod",
    "dashboard_access_method",
    "record_dashboard_access",
    "record_dashboard_cache_outcome",
    "record_dashboard_view",
]
