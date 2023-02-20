from typing import Callable, Dict, List, Optional

import structlog

from posthog.constants import (
    BREAKDOWN,
    BREAKDOWN_TYPE,
    DATE_FROM,
    DISPLAY,
    INSIGHT,
    INSIGHT_TRENDS,
    INTERVAL,
    PROPERTIES,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_BAR_VALUE,
    TRENDS_BOLD_NUMBER,
    TRENDS_WORLD_MAP,
    UNIQUE_USERS,
    AvailableFeature,
)
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.tag import Tag

DASHBOARD_COLORS: List[str] = ["white", "blue", "green", "purple", "black"]

logger = structlog.get_logger(__name__)

# TODO remove these old methods when the dashboard_templates feature flag is rolled out


def _create_website_dashboard(dashboard: Dashboard) -> None:
    dashboard.filters = {DATE_FROM: "-30d"}
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        tag, _ = Tag.objects.get_or_create(
            name="marketing", team_id=dashboard.team_id, defaults={"team_id": dashboard.team_id}
        )
        dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save(update_fields=["filters"])

    # row 1
    _create_tile_for_insight(
        dashboard,
        name="Website Unique Users (Total)",
        description="Shows the number of unique users that use your app every day.",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": UNIQUE_USERS, "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_BOLD_NUMBER,
            "compare": True,
        },
        layouts={
            "sm": {"i": "21", "x": 0, "y": 0, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 0,
                "i": "21",
                "minW": 1,
                "minH": 5,
            },
        },
        color="blue",
    )

    _create_tile_for_insight(
        dashboard,
        name="Organic SEO Unique Users (Total)",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": UNIQUE_USERS, "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_BOLD_NUMBER,
            "compare": True,
            PROPERTIES: {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$referring_domain", "type": "event", "value": "google", "operator": "icontains"},
                            {"key": "utm_source", "type": "event", "value": "is_not_set", "operator": "is_not_set"},
                        ],
                    }
                ],
            },
        },
        layouts={
            "sm": {"i": "22", "x": 6, "y": 0, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 5,
                "i": "22",
                "minW": 1,
                "minH": 5,
            },
        },
        color="green",
    )

    # row 2
    _create_tile_for_insight(
        dashboard,
        name="Website Unique Users (Breakdown)",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": UNIQUE_USERS, "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: "ActionsBar",
        },
        layouts={
            "sm": {"i": "23", "x": 0, "y": 5, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 10,
                "i": "23",
                "minW": 1,
                "minH": 5,
            },
        },
        color="blue",
    )

    _create_tile_for_insight(
        dashboard,
        name="Organic SEO Unique Users (Breakdown)",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "type": TREND_FILTER_TYPE_EVENTS,
                    PROPERTIES: [
                        {"key": "$referring_domain", "type": "event", "value": "google", "operator": "icontains"},
                        {"key": "utm_source", "type": "event", "value": "is_not_set", "operator": "is_not_set"},
                    ],
                }
            ],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: "ActionsBar",
        },
        layouts={
            "sm": {"i": "24", "x": 6, "y": 5, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {"w": 1, "h": 5, "x": 0, "y": 15, "i": "24", "minW": 1, "minH": 5},
        },
        color="green",
    )

    # row 3

    _create_tile_for_insight(
        dashboard,
        name="Sessions Per User",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 0,
                    PROPERTIES: [],
                },
                {
                    "id": "$pageview",
                    "math": "unique_session",
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 1,
                    PROPERTIES: [],
                },
            ],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: "ActionsLineGraph",
            "formula": "B/A",
        },
        layouts={
            "sm": {"i": "25", "x": 0, "y": 10, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 20,
                "i": "25",
                "minW": 1,
                "minH": 5,
            },
        },
        color=None,
    )

    _create_tile_for_insight(
        dashboard,
        name="Pages Per User",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": "total",
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 0,
                    PROPERTIES: [],
                },
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 1,
                    PROPERTIES: [],
                },
            ],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: "ActionsLineGraph",
            "formula": "A/B",
        },
        layouts={
            "sm": {"i": "26", "x": 6, "y": 10, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 25,
                "i": "26",
                "minW": 1,
                "minH": 5,
            },
        },
        color=None,
    )

    # row 4

    _create_tile_for_insight(
        dashboard,
        name="Top Website Pages (Overall)",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": "unique_session",
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 0,
                }
            ],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_BAR_VALUE,
            BREAKDOWN: "$current_url",
            BREAKDOWN_TYPE: "event",
            PROPERTIES: {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "$current_url", "type": "event", "value": "?", "operator": "not_icontains"}],
                    }
                ],
            },
        },
        layouts={
            "sm": {"i": "27", "x": 0, "y": 15, "w": 6, "h": 8, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 30,
                "i": "27",
                "minW": 1,
                "minH": 5,
            },
        },
        color="black",
    )

    _create_tile_for_insight(
        dashboard,
        name="Top Website Pages (via Google)",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": "unique_session",
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 0,
                }
            ],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_BAR_VALUE,
            BREAKDOWN: "$current_url",
            BREAKDOWN_TYPE: "event",
            PROPERTIES: {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$current_url", "type": "event", "value": "?", "operator": "not_icontains"},
                            {"key": "$referring_domain", "type": "event", "value": "google", "operator": "icontains"},
                        ],
                    }
                ],
            },
        },
        layouts={
            "sm": {"i": "28", "x": 6, "y": 15, "w": 6, "h": 8, "minW": 3, "minH": 5},
            "xs": {"w": 1, "h": 5, "x": 0, "y": 35, "i": "28", "minW": 1, "minH": 5},
        },
        color="black",
    )

    # row 5

    _create_tile_for_insight(
        dashboard,
        name="Website Users by Location",
        description="",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "name": "$pageview",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    "order": 0,
                }
            ],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_WORLD_MAP,
            BREAKDOWN: "$geoip_country_code",
            BREAKDOWN_TYPE: "person",
        },
        layouts={
            "sm": {"i": "29", "x": 0, "y": 23, "w": 12, "h": 8, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 40,
                "i": "29",
                "minW": 1,
                "minH": 5,
            },
        },
        color=None,
    )


def _create_default_app_items(dashboard: Dashboard) -> None:
    template = DashboardTemplate.original_template()
    _create_from_template(dashboard, template)


DASHBOARD_TEMPLATES: Dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
    "WEBSITE_TRAFFIC": _create_website_dashboard,
}

# end of area to be removed


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


def _create_from_template_json(dashboard: Dashboard, template: any) -> None:
    dashboard.name = template["template_name"]
    dashboard.filters = template["dashboard_filters"]
    dashboard.description = template["dashboard_description"]
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        for template_tag in template["tags"]:
            tag, _ = Tag.objects.get_or_create(
                name=template_tag, team_id=dashboard.team_id, defaults={"team_id": dashboard.team_id}
            )
            dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save()

    for template_tile in template["tiles"]:
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
    if template_key in DASHBOARD_TEMPLATES:
        return DASHBOARD_TEMPLATES[template_key](dashboard)

    template = DashboardTemplate.objects.filter(template_name=template_key).first()
    if not template:
        original_template = DashboardTemplate.original_template()
        if template_key == original_template.template_name:
            template = original_template
        else:
            raise AttributeError(f"Invalid template key `{template_key}` provided.")

    _create_from_template(dashboard, template)
