"""Business logic for cross_project_dashboards."""

from products.cross_project_dashboards.backend.logic.access import assert_can_reference_insight
from products.cross_project_dashboards.backend.logic.filters import validate_cross_project_filters

__all__ = ["assert_can_reference_insight", "validate_cross_project_filters"]
