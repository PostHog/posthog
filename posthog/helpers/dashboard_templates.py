from typing import Optional
from collections.abc import Callable

import structlog

from posthog.constants import (
    AvailableFeature,
    ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER,
)
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.dashboard_tile import DashboardTile, Text
from posthog.models.insight import Insight
from posthog.models.tag import Tag

DASHBOARD_COLORS: list[str] = ["white", "blue", "green", "purple", "black"]

logger = structlog.get_logger(__name__)

# TODO remove these old methods when the dashboard_templates feature flag is rolled out


def _create_website_dashboard(dashboard: Dashboard) -> None:
    dashboard.filters = {"date_from": "-30d"}
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        tag, _ = Tag.objects.get_or_create(
            name="marketing",
            team_id=dashboard.team_id,
            defaults={"team_id": dashboard.team_id},
        )
        dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save(update_fields=["filters"])

    # row 1
    _create_tile_for_insight(
        dashboard,
        name="Website Unique Users (Total)",
        description="Shows the number of unique users that use your app every day.",
        filters={
            "events": [
                {
                    "id": "$pageview",
                    "math": "dau",
                    "type": "events",
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "BoldNumber",
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "dau",
                    "type": "events",
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "BoldNumber",
            "compare": True,
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$referring_domain",
                                "type": "event",
                                "value": "google",
                                "operator": "icontains",
                            },
                            {
                                "key": "utm_source",
                                "type": "event",
                                "value": "is_not_set",
                                "operator": "is_not_set",
                            },
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "dau",
                    "type": "events",
                }
            ],
            "interval": "week",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsBar",
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "dau",
                    "type": "events",
                    "properties": [
                        {
                            "key": "$referring_domain",
                            "type": "event",
                            "value": "google",
                            "operator": "icontains",
                        },
                        {
                            "key": "utm_source",
                            "type": "event",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                }
            ],
            "interval": "week",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsBar",
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "dau",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                    "properties": [],
                },
                {
                    "id": "$pageview",
                    "math": "unique_session",
                    "name": "$pageview",
                    "type": "events",
                    "order": 1,
                    "properties": [],
                },
            ],
            "interval": "week",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsLineGraph",
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "total",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                    "properties": [],
                },
                {
                    "id": "$pageview",
                    "math": "dau",
                    "name": "$pageview",
                    "type": "events",
                    "order": 1,
                    "properties": [],
                },
            ],
            "interval": "week",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsLineGraph",
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "unique_session",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsBarValue",
            "breakdown": "$current_url",
            "breakdown_type": "event",
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "?",
                                "operator": "not_icontains",
                            }
                        ],
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "unique_session",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsBarValue",
            "breakdown": "$current_url",
            "breakdown_type": "event",
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "?",
                                "operator": "not_icontains",
                            },
                            {
                                "key": "$referring_domain",
                                "type": "event",
                                "value": "google",
                                "operator": "icontains",
                            },
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
            "events": [
                {
                    "id": "$pageview",
                    "math": "dau",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "WorldMap",
            "breakdown": "$geoip_country_code",
            "breakdown_type": "person",
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
    create_from_template(dashboard, template)


DASHBOARD_TEMPLATES: dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
    "WEBSITE_TRAFFIC": _create_website_dashboard,
}

# end of area to be removed


def create_from_template(dashboard: Dashboard, template: DashboardTemplate) -> None:
    if not dashboard.name or dashboard.name == "":
        dashboard.name = template.template_name
    dashboard.filters = template.dashboard_filters
    dashboard.description = template.dashboard_description
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        for template_tag in template.tags or []:
            tag, _ = Tag.objects.get_or_create(
                name=template_tag,
                team_id=dashboard.team_id,
                defaults={"team_id": dashboard.team_id},
            )
            dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save()

    for template_tile in template.tiles:
        if template_tile["type"] == "insight":
            query = template_tile.get("query", None)
            filters = template_tile.get("filters") if not query else {}
            _create_tile_for_insight(
                dashboard,
                name=template_tile.get("name"),
                filters=filters,
                query=query,
                description=template_tile.get("description"),
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
            )
        elif template_tile["type"] == "TEXT":
            _create_tile_for_text(
                dashboard,
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
                body=template_tile.get("body"),
            )
        else:
            logger.error("dashboard_templates.creation.unknown_type", template=template)


def _create_tile_for_text(dashboard: Dashboard, body: str, layouts: dict, color: Optional[str]) -> None:
    text = Text.objects.create(
        team=dashboard.team,
        body=body,
    )
    DashboardTile.objects.create(
        text=text,
        dashboard=dashboard,
        layouts=layouts,
        color=color,
    )


def _create_tile_for_insight(
    dashboard: Dashboard,
    name: str,
    filters: dict,
    description: str,
    layouts: dict,
    color: Optional[str],
    query: Optional[dict] = None,
) -> None:
    filter_test_accounts = filters.get("filter_test_accounts", True)
    insight = Insight.objects.create(
        team=dashboard.team,
        name=name,
        description=description,
        filters={**filters, "filter_test_accounts": filter_test_accounts},
        is_sample=True,
        query=query,
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

    create_from_template(dashboard, template)


def create_feature_flag_dashboard(feature_flag, dashboard: Dashboard) -> None:
    dashboard.filters = {"date_from": "-30d"}
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        tag, _ = Tag.objects.get_or_create(
            name="feature flags",
            team_id=dashboard.team_id,
            defaults={"team_id": dashboard.team_id},
        )
        dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save(update_fields=["filters"])

    # 1 row
    _create_tile_for_insight(
        dashboard,
        name="Feature Flag Called Total Volume",
        description="Shows the number of total calls made on feature flag with key: " + feature_flag.key,
        filters={
            "events": [
                {
                    "id": "$feature_flag_called",
                    "name": "$feature_flag_called",
                    "type": "events",
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsLineGraph",
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$feature_flag",
                                "type": "event",
                                "value": feature_flag.key,
                            },
                        ],
                    }
                ],
            },
            "breakdown": "$feature_flag_response",
            "breakdown_type": "event",
            "filter_test_accounts": False,
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
        name="Feature Flag calls made by unique users per variant",
        description="Shows the number of unique user calls made on feature flag per variant with key: "
        + feature_flag.key,
        filters={
            "events": [
                {
                    "id": "$feature_flag_called",
                    "name": "$feature_flag_called",
                    "math": "dau",
                    "type": "events",
                }
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsTable",
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$feature_flag",
                                "type": "event",
                                "value": feature_flag.key,
                            },
                        ],
                    }
                ],
            },
            "breakdown": "$feature_flag_response",
            "breakdown_type": "event",
            "filter_test_accounts": False,
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


def add_enriched_insights_to_feature_flag_dashboard(feature_flag, dashboard: Dashboard) -> None:
    # 1 row
    _create_tile_for_insight(
        dashboard,
        name=f"{ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER} Total Volume",
        description="Shows the total number of times this feature was viewed and interacted with",
        filters={
            "events": [
                {
                    "id": "$feature_view",
                    "name": "Feature View - Total",
                    "type": "events",
                },
                {
                    "id": "$feature_view",
                    "name": "Feature View - Unique users",
                    "type": "events",
                    "math": "dau",
                },
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsLineGraph",
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "feature_flag",
                                "type": "event",
                                "value": feature_flag.key,
                            },
                        ],
                    }
                ],
            },
            "filter_test_accounts": False,
        },
        layouts={},
        color=None,
    )

    _create_tile_for_insight(
        dashboard,
        name="Feature Interaction Total Volume",
        description="Shows the total number of times this feature was viewed and interacted with",
        filters={
            "events": [
                {
                    "id": "$feature_interaction",
                    "name": "Feature Interaction - Total",
                    "type": "events",
                },
                {
                    "id": "$feature_interaction",
                    "name": "Feature Interaction - Unique users",
                    "type": "events",
                    "math": "dau",
                },
            ],
            "interval": "day",
            "insight": "TRENDS",
            "date_from": "-30d",
            "display": "ActionsLineGraph",
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "feature_flag",
                                "type": "event",
                                "value": feature_flag.key,
                            },
                        ],
                    }
                ],
            },
            "filter_test_accounts": False,
        },
        layouts={},
        color=None,
    )
