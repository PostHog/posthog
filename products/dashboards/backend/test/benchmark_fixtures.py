"""Fixtures for the dashboard-v2 scorecard in `products/dashboards/backend/benchmarks/`.

The scorecard runs under pytest against the test database, so it builds its boards the way tests do.
"""

from typing import Any

from posthog.models import Team, User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


def create_insight_tiles(
    team: Team, user: User, dashboard: Dashboard, queries: list[tuple[str, dict[str, Any]]]
) -> list[DashboardTile]:
    """One insight tile on `dashboard` per (name, query) pair, in order."""
    tiles = []
    for name, query in queries:
        insight = Insight.objects.create(team=team, name=name, created_by=user, query=query)
        tiles.append(DashboardTile.objects.create(dashboard=dashboard, insight=insight))
    return tiles
