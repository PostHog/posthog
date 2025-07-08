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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "compareFilter": {"compare": True},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "BoldNumber",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "compareFilter": {"compare": True},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$referring_domain",
                                    "operator": "icontains",
                                    "type": "event",
                                    "value": "google",
                                },
                                {"key": "utm_source", "operator": "is_not_set", "type": "event", "value": "is_not_set"},
                            ],
                        }
                    ],
                },
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "BoldNumber",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBar",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [
                    {
                        "event": "$pageview",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "$pageview",
                        "properties": [
                            {"key": "$referring_domain", "operator": "icontains", "type": "event", "value": "google"},
                            {"key": "utm_source", "operator": "is_not_set", "type": "event", "value": "is_not_set"},
                        ],
                    }
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBar",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [
                    {"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"},
                    {"event": "$pageview", "kind": "EventsNode", "math": "unique_session", "name": "$pageview"},
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "formula": "B/A",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [
                    {"event": "$pageview", "kind": "EventsNode", "math": "total", "name": "$pageview"},
                    {"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"},
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "formula": "A/B",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$current_url", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "$current_url", "operator": "not_icontains", "type": "event", "value": "?"}
                            ],
                        }
                    ],
                },
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "unique_session", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBarValue",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$current_url", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "$current_url", "operator": "not_icontains", "type": "event", "value": "?"},
                                {
                                    "key": "$referring_domain",
                                    "operator": "icontains",
                                    "type": "event",
                                    "value": "google",
                                },
                            ],
                        }
                    ],
                },
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "unique_session", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBarValue",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
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
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$geoip_country_code", "breakdown_type": "person"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "WorldMap",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        if template_tile["type"] == "INSIGHT":
            query = template_tile.get("query", None)
            _create_tile_for_insight(
                dashboard,
                name=template_tile.get("name"),
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
    description: str,
    layouts: dict,
    color: Optional[str],
    query: Optional[dict] = None,
    user=None,
) -> None:
    insight = Insight.objects.create(
        team=dashboard.team,
        name=name,
        description=description,
        is_sample=True,
        query=query,
        created_by=user,
        last_modified_by=user,
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


FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME = "Feature Flag Called Total Volume"
FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME = "Feature Flag calls made by unique users per variant"


def create_feature_flag_dashboard(feature_flag, dashboard: Dashboard, user) -> None:
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
        name=FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME,
        description=_get_feature_flag_total_volume_insight_description(feature_flag.key),
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$feature_flag_response", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag",
                                    "operator": "exact",
                                    "type": "event",
                                    "value": feature_flag.key,
                                }
                            ],
                        }
                    ],
                },
                "series": [{"event": "$feature_flag_called", "kind": "EventsNode", "name": "$feature_flag_called"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
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
        user=user,
    )

    _create_tile_for_insight(
        dashboard,
        name=FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME,
        description=_get_feature_flag_unique_users_insight_description(feature_flag.key),
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$feature_flag_response", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag",
                                    "operator": "exact",
                                    "type": "event",
                                    "value": feature_flag.key,
                                }
                            ],
                        }
                    ],
                },
                "series": [
                    {
                        "event": "$feature_flag_called",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "$feature_flag_called",
                    }
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsTable",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
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
        user=user,
    )


def create_group_type_mapping_detail_dashboard(group_type_mapping, user) -> Dashboard:
    singular = group_type_mapping.name_singular or group_type_mapping.group_type
    plural = group_type_mapping.name_plural or group_type_mapping.group_type + "s"

    dashboard = Dashboard.objects.create(
        name=f"Template dashboard for {singular} overview",
        description=f"This dashboard template powers the Overview page for all {plural}. Any insights will automatically filter to the selected {singular}.",
        team=group_type_mapping.team,
        created_by=user,
        creation_mode="template",
    )

    configurations = [
        {
            "name": "Top paths",
            "description": f"Shows the most popular pages viewed by this {singular} in the last 30 days",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "properties": [
                                {
                                    "key": "$pathname",
                                    "value": ["/"],
                                    "operator": "is_not",
                                    "type": "event",
                                },
                            ],
                            "math": "unique_session",
                        },
                    ],
                    "trendsFilter": {
                        "display": "ActionsBarValue",
                    },
                    "breakdownFilter": {
                        "breakdown": "$pathname",
                        "breakdown_type": "event",
                    },
                    "dateRange": {
                        "date_from": "-30d",
                        "date_to": None,
                        "explicitDate": False,
                    },
                    "interval": "day",
                },
                "full": True,
            },
        },
        {
            "name": "Top events",
            "description": f"Shows the most popular events by this {singular} in the last 30 days",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": None, "name": "All events", "properties": [], "math": "total"}
                    ],
                    "trendsFilter": {"display": "ActionsBarValue"},
                    "breakdownFilter": {"breakdowns": [{"property": "event", "type": "event_metadata"}]},
                    "dateRange": {"date_from": "-30d", "date_to": None, "explicitDate": False},
                    "interval": "day",
                },
                "full": True,
            },
        },
        {
            "name": "Weekly active users",
            "description": f"Shows the number of unique users from this {singular} in the last 90 days",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "dateRange": {"date_from": "-90d", "explicitDate": False},
                    "filterTestAccounts": False,
                    "interval": "week",
                    "kind": "TrendsQuery",
                    "properties": [],
                    "series": [{"event": None, "kind": "EventsNode", "math": "dau"}],
                    "trendsFilter": {
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsLineGraph",
                        "showAlertThresholdLines": False,
                        "showLegend": False,
                        "showPercentStackView": False,
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "yAxisScaleType": "linear",
                    },
                },
            },
        },
        {
            "name": "Monthly active users",
            "description": f"Shows the number of unique users from this {singular} in the last year",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "dateRange": {"date_from": "-365d", "explicitDate": False},
                    "filterTestAccounts": False,
                    "interval": "month",
                    "kind": "TrendsQuery",
                    "properties": [],
                    "series": [{"event": None, "kind": "EventsNode", "math": "dau"}],
                    "trendsFilter": {
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsLineGraph",
                        "showAlertThresholdLines": False,
                        "showLegend": False,
                        "showPercentStackView": False,
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "yAxisScaleType": "linear",
                    },
                },
            },
        },
        {
            "name": "Retained users",
            "description": f"Shows the number of users from this {singular} who returned seven days after their first visit",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {
                        "period": "Day",
                        "targetEntity": {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                        },
                        "retentionType": "retention_first_time",
                        "totalIntervals": 8,
                        "returningEntity": {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                        },
                        "meanRetentionCalculation": "simple",
                    },
                },
            },
        },
    ]

    for index, configuration in enumerate(configurations):
        x = 6 if index % 2 == 1 else 0
        y = 5 * (index // 2)
        insight = Insight.objects.create(
            team=dashboard.team,
            name=str(configuration["name"]),
            description=str(configuration["description"]),
            is_sample=True,
            query=configuration["query"],
        )
        tile = DashboardTile.objects.create(
            insight=insight,
            dashboard=dashboard,
            layouts={
                "sm": {"h": 5, "w": 6, "x": x, "y": y, "minH": 1, "minW": 1},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 1, "minW": 1},
            },
            color=None,
        )
        tile.layouts = {
            "sm": {
                "h": 5,
                "i": str(tile.id),
                "w": 6,
                "x": x,
                "y": y,
                "minH": 1,
                "minW": 1,
            },
            "xs": {"h": 5, "i": str(tile.id), "w": 1, "x": 0, "y": 0, "minH": 1, "minW": 1},
        }
        tile.last_refresh = None
        tile.save()

    return dashboard


def _get_feature_flag_total_volume_insight_description(feature_flag_key: str) -> str:
    return f"Shows the number of total calls made on feature flag with key: {feature_flag_key}"


def _get_feature_flag_unique_users_insight_description(feature_flag_key: str) -> str:
    return f"Shows the number of unique user calls made on feature flag per variant with key: {feature_flag_key}"


def update_feature_flag_dashboard(feature_flag, old_key: str) -> None:
    # We need to update the *system* created insights with the new key, so we search for them by name
    dashboard = feature_flag.usage_dashboard

    if not dashboard:
        return

    total_volume_insight = dashboard.insights.filter(name=FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME).first()
    if total_volume_insight:
        _update_tile_with_new_key(
            total_volume_insight,
            feature_flag.key,
            old_key,
            _get_feature_flag_total_volume_insight_description,
        )

    unique_users_insight = dashboard.insights.filter(name=FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME).first()
    if unique_users_insight:
        _update_tile_with_new_key(
            unique_users_insight,
            feature_flag.key,
            old_key,
            _get_feature_flag_unique_users_insight_description,
        )


def _update_tile_with_new_key(insight, new_key: str, old_key: str, descriptionFunction: Callable[[str], str]) -> None:
    old_description = descriptionFunction(old_key)
    new_description = descriptionFunction(new_key)

    if insight.description != old_description:  # We don't touch insights that have been manually edited
        return

    if insight.query:
        property_values = insight.query.get("source", {}).get("properties", {}).get("values", [])
        if len(property_values) != 1:  # Exit if not exactly one property group
            return

        property_group = property_values[0]
        values = property_group.get("values", [])
        # Only proceed if there's exactly one value and it's a feature flag
        if len(values) == 1 and values[0].get("key") == "$feature_flag" and values[0].get("value") == old_key:
            values[0]["value"] = new_key
            insight.query = insight.query  # Trigger field update
            # Only update the insight if it matches what we expect for the system created insights
            insight.description = new_description
            insight.save()
            return


def add_enriched_insights_to_feature_flag_dashboard(feature_flag, dashboard: Dashboard) -> None:
    # 1 row
    _create_tile_for_insight(
        dashboard,
        name=f"{ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER} Total Volume",
        description="Shows the total number of times this feature was viewed and interacted with",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "feature_flag", "operator": "exact", "type": "event", "value": feature_flag.key}
                            ],
                        }
                    ],
                },
                "series": [
                    {"event": "$feature_view", "kind": "EventsNode", "name": "Feature View - Total"},
                    {
                        "event": "$feature_view",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "Feature View - Unique users",
                    },
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={},
        color=None,
    )

    _create_tile_for_insight(
        dashboard,
        name="Feature Interaction Total Volume",
        description="Shows the total number of times this feature was viewed and interacted with",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "feature_flag", "operator": "exact", "type": "event", "value": feature_flag.key}
                            ],
                        }
                    ],
                },
                "series": [
                    {"event": "$feature_interaction", "kind": "EventsNode", "name": "Feature Interaction - Total"},
                    {
                        "event": "$feature_interaction",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "Feature Interaction - Unique users",
                    },
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={},
        color=None,
    )
