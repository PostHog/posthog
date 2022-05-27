from typing import Callable, Dict, List

from django.utils.timezone import now

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
    RETENTION_FIRST_TIME,
    RETENTION_TYPE,
    RETURNING_ENTITY,
    SHOWN_AS,
    TARGET_ENTITY,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_BAR_VALUE,
    TRENDS_FUNNEL,
    TRENDS_LIFECYCLE,
    FunnelVizType,
)
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight

DASHBOARD_COLORS: List[str] = ["white", "blue", "green", "purple", "black"]


def _create_default_app_items(dashboard: Dashboard) -> None:

    insight = Insight.objects.create(
        team=dashboard.team,
        name="Daily active users (DAUs)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        description="Shows the number of unique users that use your app every day.",
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        color="blue",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3, "moved": False, "static": False},
        },
    )

    insight = Insight.objects.create(
        team=dashboard.team,
        name="Weekly active users (WAUs)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "weekly_active", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "week",
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        description="Shows the number of unique users that use your app every week.",
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        color="green",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3, "moved": False, "static": False},
        },
    )

    insight = Insight.objects.create(
        team=dashboard.team,
        name="Retention",
        filters={
            TARGET_ENTITY: {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS},
            RETURNING_ENTITY: {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS},
            PERIOD: "Week",
            RETENTION_TYPE: RETENTION_FIRST_TIME,
            INSIGHT: INSIGHT_RETENTION,
        },
        last_refresh=now(),
        description="Weekly retention of your users.",
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        color="blue",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3, "moved": False, "static": False},
        },
    )

    insight = Insight.objects.create(
        team=dashboard.team,
        name="Growth accounting",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}],
            ENTITY_TYPE: TREND_FILTER_TYPE_EVENTS,
            INTERVAL: "week",
            SHOWN_AS: TRENDS_LIFECYCLE,
            INSIGHT: INSIGHT_LIFECYCLE,
            DATE_FROM: "-30d",
        },
        last_refresh=now(),
        description="How many of your users are new, returning, resurrecting, or dormant each week.",
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        color="purple",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3, "moved": False, "static": False},
        },
    )

    insight = Insight.objects.create(
        team=dashboard.team,
        name="Referring domain (last 14 days)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
            DISPLAY: TRENDS_BAR_VALUE,
            BREAKDOWN: "$referring_domain",
            DATE_FROM: "-14d",
            BREAKDOWN_TYPE: "event",
        },
        last_refresh=now(),
        description="Shows the most common referring domains for your users over the past 14 days.",
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        color="black",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 0, "y": 10, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 3, "moved": False, "static": False},
        },
    )

    insight = Insight.objects.create(
        team=dashboard.team,
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
        last_refresh=now(),
        is_sample=True,
        description="This example funnel shows how many of your users have completed 3 page views, broken down by browser.",
    )
    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        color="green",
        layouts={
            "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3, "moved": False, "static": False},
        },
    )


DASHBOARD_TEMPLATES: Dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
}


def create_dashboard_from_template(template_key: str, dashboard: Dashboard) -> None:

    if template_key not in DASHBOARD_TEMPLATES:
        raise AttributeError(f"Invalid template key `{template_key}` provided.")

    DASHBOARD_TEMPLATES[template_key](dashboard)
