from __future__ import annotations

from typing import TYPE_CHECKING

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

if TYPE_CHECKING:
    from posthog.models.team.team import Team


def create_signup_primary_dashboard(team: Team, *, using: str | None = None) -> Dashboard:
    from posthog.helpers.dashboard_templates import create_from_template  # noqa: PLC0415 — breaks team import cycle

    template = DashboardTemplate.default_signup_template()

    dashboard = Dashboard.objects.db_manager(using).create(
        name="Your starter dashboard",
        pinned=True,
        team=team,
        description=template.dashboard_description or "",
    )
    create_from_template(dashboard, template)
    return dashboard
