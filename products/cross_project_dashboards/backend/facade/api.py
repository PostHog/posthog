"""
Facade for cross_project_dashboards.

The ONLY module other products are allowed to import, and the only module the presentation
layer reaches internals through.

No other product consumes this one yet, so the surface is what presentation needs.
"""

from products.cross_project_dashboards.backend.logic.access import assert_can_reference_insight
from products.cross_project_dashboards.backend.logic.filters import validate_cross_project_filters
from products.cross_project_dashboards.backend.models import CrossProjectDashboard, CrossProjectDashboardTile

__all__ = [
    "CrossProjectDashboard",
    "CrossProjectDashboardTile",
    "assert_can_reference_insight",
    "validate_cross_project_filters",
]
