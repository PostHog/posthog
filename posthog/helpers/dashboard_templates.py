from typing import Dict, List, Optional

import structlog

from posthog.constants import AvailableFeature
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.tag import Tag

DASHBOARD_COLORS: List[str] = ["white", "blue", "green", "purple", "black"]

logger = structlog.get_logger(__name__)


def _create_from_template(dashboard: Dashboard, template: DashboardTemplate) -> None:
    dashboard.filters = template.dashboard_filters
    dashboard.description = template.dashboard_description
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        for template_tag in template.tags:
            tag, _ = Tag.objects.get_or_create(
                name=template_tag, team_id=dashboard.team_id, defaults={"team_id": dashboard.team_id}
            )
            dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save(update_fields=["filters", "description"])

    for template_tile in template.tiles:
        if template_tile["type"] == "INSIGHT":
            _create_tile_for_insight(
                dashboard,
                name=template_tile.get("name"),
                filters=template_tile.get("filters"),
                description=template_tile.get("description"),
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
            )
        elif template_tile["type"] == "TEXT":
            # TODO support text tiles
            pass
        else:
            logger.error("dashboard_templates.creation.unknown_type", template=template)


def _create_tile_for_insight(
    dashboard: Dashboard, name: str, filters: Dict, description: str, layouts: Dict, color: Optional[str]
) -> None:
    insight = Insight.objects.create(
        team=dashboard.team,
        name=name,
        description=description,
        filters={**filters, "filter_test_accounts": True},
        is_sample=True,
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        layouts=layouts,
        color=color,
    )


def create_dashboard_from_template(template_key: str, dashboard: Dashboard) -> None:

    template = DashboardTemplate.objects.filter(template_name=template_key).first()
    if not template:
        original_template = DashboardTemplate.original_template()
        if template_key == original_template.template_name:
            template = original_template
        else:
            raise AttributeError(f"Invalid template key `{template_key}` provided.")

    _create_from_template(dashboard, template)
