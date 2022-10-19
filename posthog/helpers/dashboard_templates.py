from typing import Callable, Dict, List, Optional

from posthog.constants import (
    BREAKDOWN,
    BREAKDOWN_TYPE,
    BREAKDOWNS,
    DATE_FROM,
    DISPLAY,
    ENTITY_TYPE,
    EXCLUSIONS,
    FUNNEL_LAYOUT,
    FUNNEL_VIZ_TYPE,
    INSIGHT,
    INSIGHT_LIFECYCLE,
    INSIGHT_RETENTION,
    INSIGHT_TRENDS,
    INTERVAL,
    PERIOD,
    PROPERTIES,
    RETENTION_FIRST_TIME,
    RETENTION_TYPE,
    RETURNING_ENTITY,
    SHOWN_AS,
    TARGET_ENTITY,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_BAR_VALUE,
    TRENDS_BOLD_NUMBER,
    TRENDS_FUNNEL,
    TRENDS_LIFECYCLE,
    TRENDS_WORLD_MAP,
    UNIQUE_USERS,
    AvailableFeature,
    FunnelVizType,
)
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.tag import Tag

DASHBOARD_COLORS: List[str] = ["white", "blue", "green", "purple", "black"]


def _create_website_dashboard(dashboard: Dashboard) -> None:
    dashboard.filters = {DATE_FROM: "-30d"}
    if dashboard.team.organization.is_feature_available(AvailableFeature.TAGGING):
        tag, _ = Tag.objects.get_or_create(name="marketing", defaults={"team_id": dashboard.team_id})
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
            "sm": {
                "h": 5,
                "w": 4,
                "x": 0,
                "y": 0,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
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
            "sm": {"h": 5, "w": 4, "x": 4, "y": 0, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
        },
        color="green",
    )

    _create_tile_for_insight(
        dashboard,
        name="Blog Unique Users (Total)",
        description="Page view events where url contains blog.",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "type": TREND_FILTER_TYPE_EVENTS,
                    PROPERTIES: [{"key": "$current_url", "type": "event", "value": "blog", "operator": "icontains"}],
                }
            ],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_BOLD_NUMBER,
            "compare": True,
        },
        layouts={
            "sm": {"h": 5, "w": 4, "x": 8, "y": 0, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3},
        },
        color="purple",
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
            "sm": {
                "h": 5,
                "w": 4,
                "x": 0,
                "y": 5,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3},
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
            "sm": {
                "h": 5,
                "w": 4,
                "x": 4,
                "y": 5,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 3},
        },
        color="green",
    )

    _create_tile_for_insight(
        dashboard,
        name="Blog Unique Users (Breakdown)",
        description="Page view events where url contains blog.",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "type": TREND_FILTER_TYPE_EVENTS,
                    PROPERTIES: [{"key": "$current_url", "type": "event", "value": "blog", "operator": "icontains"}],
                }
            ],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: "ActionsBar",
        },
        layouts={
            "sm": {
                "h": 5,
                "w": 4,
                "x": 8,
                "y": 5,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3},
        },
        color="purple",
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
            "sm": {
                "h": 5,
                "i": "91",
                "w": 6,
                "x": 0,
                "y": 10,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "i": "91", "w": 1, "x": 0, "y": 170, "minH": 5, "minW": 1},
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
            "sm": {
                "h": 5,
                "i": "92",
                "w": 6,
                "x": 6,
                "y": 10,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "i": "92", "w": 1, "x": 0, "y": 175, "minH": 5, "minW": 1},
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
            "sm": {
                "h": 8,
                "i": "93",
                "w": 6,
                "x": 0,
                "y": 15,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "i": "93", "w": 1, "x": 0, "y": 45, "minH": 5, "minW": 1},
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
            "sm": {
                "h": 8,
                "i": "94",
                "w": 6,
                "x": 6,
                "y": 15,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "i": "94", "w": 1, "x": 0, "y": 50, "minH": 5, "minW": 1},
        },
        color="black",
    )

    # row 5

    _create_tile_for_insight(
        dashboard,
        name="Top Blog Pages (Overall)",
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
                            {"key": "$current_url", "type": "event", "value": "blog", "operator": "icontains"},
                            {"key": "$current_url", "type": "event", "value": "?", "operator": "not_icontains"},
                        ],
                    }
                ],
            },
        },
        layouts={
            "sm": {
                "h": 8,
                "i": "95",
                "w": 6,
                "x": 0,
                "y": 23,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "i": "95", "w": 1, "x": 0, "y": 55, "minH": 5, "minW": 1},
        },
        color="purple",
    )

    _create_tile_for_insight(
        dashboard,
        name="Top Blog Pages (via Google)",
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
                            {"key": "$current_url", "type": "event", "value": "blog", "operator": "icontains"},
                            {"key": "$referring_domain", "type": "event", "value": "google", "operator": "icontains"},
                        ],
                    }
                ],
            },
        },
        layouts={
            "sm": {"h": 8, "w": 6, "x": 6, "y": 52, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 35, "minH": 5, "minW": 3},
        },
        color="purple",
    )

    # row 6

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
            "sm": {
                "h": 8,
                "w": 12,
                "x": 0,
                "y": 84,
                "minH": 5,
                "minW": 3,
            },
            "xs": {"h": 5, "w": 1, "x": 0, "y": 90, "minH": 5, "minW": 3},
        },
        color=None,
    )


def _create_default_app_items(dashboard: Dashboard) -> None:

    _create_tile_for_insight(
        dashboard,
        name="Daily active users (DAUs)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {
                    "id": "$pageview",
                    "math": UNIQUE_USERS,
                    "type": TREND_FILTER_TYPE_EVENTS,
                }
            ],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_BOLD_NUMBER,
        },
        description="Shows the number of unique users that use your app every day.",
        color="blue",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
            "xs": {
                "h": 5,
                "w": 1,
                "x": 0,
                "y": 0,
                "minH": 5,
                "minW": 3,
            },
        },
    )

    _create_tile_for_insight(
        dashboard,
        name="Weekly active users (WAUs)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "weekly_active", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
        },
        description="Shows the number of unique users that use your app every week.",
        color="green",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
            "xs": {
                "h": 5,
                "w": 1,
                "x": 0,
                "y": 5,
                "minH": 5,
                "minW": 3,
            },
        },
    )

    _create_tile_for_insight(
        dashboard,
        name="Retention",
        filters={
            TARGET_ENTITY: {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS},
            RETURNING_ENTITY: {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS},
            PERIOD: "Week",
            RETENTION_TYPE: RETENTION_FIRST_TIME,
            INSIGHT: INSIGHT_RETENTION,
        },
        description="Weekly retention of your users.",
        color="blue",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
            "xs": {
                "h": 5,
                "w": 1,
                "x": 0,
                "y": 10,
                "minH": 5,
                "minW": 3,
            },
        },
    )

    _create_tile_for_insight(
        dashboard,
        name="Growth accounting",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}],
            ENTITY_TYPE: TREND_FILTER_TYPE_EVENTS,
            INTERVAL: "week",
            SHOWN_AS: TRENDS_LIFECYCLE,
            INSIGHT: INSIGHT_LIFECYCLE,
            DATE_FROM: "-30d",
        },
        description="How many of your users are new, returning, resurrecting, or dormant each week.",
        color="purple",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
            "xs": {
                "h": 5,
                "w": 1,
                "x": 0,
                "y": 15,
                "minH": 5,
                "minW": 3,
            },
        },
    )

    _create_tile_for_insight(
        dashboard,
        name="Referring domain (last 14 days)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": UNIQUE_USERS, "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DISPLAY: TRENDS_BAR_VALUE,
            BREAKDOWN: "$referring_domain",
            DATE_FROM: "-14d",
            BREAKDOWN_TYPE: "event",
        },
        description="Shows the most common referring domains for your users over the past 14 days.",
        color="black",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 0, "y": 10, "minH": 5, "minW": 3},
            "xs": {
                "h": 5,
                "w": 1,
                "x": 0,
                "y": 20,
                "minH": 5,
                "minW": 3,
            },
        },
    )

    _create_tile_for_insight(
        dashboard,
        name="Pageview funnel, by browser",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS, "order": 0, "custom_name": "First page view"},
                {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS, "order": 1, "custom_name": "Second page view"},
                {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS, "order": 2, "custom_name": "Third page view"},
            ],
            INSIGHT: "FUNNELS",
            FUNNEL_LAYOUT: "horizontal",
            INTERVAL: "day",
            BREAKDOWN_TYPE: "event",
            BREAKDOWNS: [{"property": "$browser", "type": "event"}],
            FUNNEL_VIZ_TYPE: FunnelVizType.STEPS,
            DISPLAY: TRENDS_FUNNEL,
            EXCLUSIONS: [],
        },
        description="This example funnel shows how many of your users have completed 3 page views, broken down by browser.",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
            "xs": {
                "h": 5,
                "w": 1,
                "x": 0,
                "y": 25,
                "minH": 5,
                "minW": 3,
            },
        },
        color="green",
    )


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


DASHBOARD_TEMPLATES: Dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
    "WEBSITE_TRAFFIC": _create_website_dashboard,
}


def create_dashboard_from_template(template_key: str, dashboard: Dashboard) -> None:

    if template_key not in DASHBOARD_TEMPLATES:
        raise AttributeError(f"Invalid template key `{template_key}` provided.")

    DASHBOARD_TEMPLATES[template_key](dashboard)
