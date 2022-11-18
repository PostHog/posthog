from typing import Dict, List

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_template import DashboardTemplate
from posthog.models.dashboard_tile import DashboardTile, Text
from posthog.models.insight import Insight
from posthog.models.tag import Tag

DASHBOARD_COLORS: List[str] = ["white", "blue", "green", "purple", "black"]


def update_using_template(dashboard: Dashboard, template: DashboardTemplate) -> None:
    dashboard.filters = template.dashboard_filters or {}

    for tag in template.tags:
        created_tag, _ = Tag.objects.get_or_create(
            name=tag, team_id=dashboard.team_id, defaults={"team_id": dashboard.team_id}
        )
        dashboard.tagged_items.create(tag_id=created_tag.id)

    dashboard.description = template.dashboard_description or ""
    dashboard.save(update_fields=["filters", "name", "description"])

    for tile in template.tiles:
        tile_type = tile.get("type", "UNKNOWN")
        if tile_type == "INSIGHT":
            _create_insight_tile(dashboard, tile)
        elif tile_type == "TEXT":
            _create_text_tile(dashboard, tile)
        else:
            raise AttributeError(f"Invalid tile type `{tile_type}` provided.")


def _create_insight_tile(dashboard: Dashboard, tile: Dict) -> None:
    insight = Insight.objects.create(
        team=dashboard.team,
        name=tile.get("name", None),
        description=tile.get("description", None),
        filters={**tile.get("filters", {}), "filter_test_accounts": True},
        is_sample=True,
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        layouts=tile.get("layouts", {}),
        color=tile.get("color", None),
    )


def _create_text_tile(dashboard: Dashboard, tile: Dict) -> None:
    text = Text.objects.create(
        team=dashboard.team,
        body=tile.get("body", None),
    )
    DashboardTile.objects.create(
        text=text,
        dashboard=dashboard,
        layouts=tile.get("layouts", {}),
        color=tile.get("color", None),
    )


def create_global_templates(templates: List[Dict]) -> None:
    for template in templates:
        DashboardTemplate.objects.get_or_create(
            template_name=template.get("name"),
            team=None,
            organization=None,
            scope=DashboardTemplate.Scope.GLOBAL,
            source_dashboard=None,
            defaults={
                "dashboard_description": template.get("description", ""),
                "dashboard_filters": template.get("filters", {}),
                "tags": template.get("tags", []),
                "tiles": template.get("tiles", []),
            },
        )


def create_dashboard_from_template(template_key: str, dashboard: Dashboard) -> None:
    try:
        template = DashboardTemplate.objects.get(id=template_key)
    except DashboardTemplate.DoesNotExist:
        raise AttributeError(f"Invalid template key `{template_key}` provided.")

    update_using_template(dashboard, template)
