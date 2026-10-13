"""
Facade re-exports for dashboard access classification and cache telemetry.

Insights render inside dashboards, so the insight API classifies how a render was reached and
records the cache outcome under the dashboards metrics. It imports both from here rather than
reaching the internal ``access`` module.
"""

from products.dashboards.backend.access import dashboard_access_method, record_dashboard_cache_outcome
from products.dashboards.backend.facade.enums import DashboardAccessMethod

__all__ = ["DashboardAccessMethod", "dashboard_access_method", "record_dashboard_cache_outcome"]
