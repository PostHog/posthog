import random
from typing import Callable, Dict, List, Optional

from django.utils.timezone import now

from posthog.constants import (
    BREAKDOWN,
    BREAKDOWN_TYPE,
    DATE_FROM,
    DISPLAY,
    ENTITY_ID,
    ENTITY_TYPE,
    INSIGHT,
    INSIGHT_TRENDS,
    INTERVAL,
    PROPERTIES,
    SHOWN_AS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_CUMULATIVE,
    TRENDS_PIE,
    TRENDS_STICKINESS,
)
from posthog.models.dashboard import Dashboard
from posthog.models.insight import Insight

DASHBOARD_COLORS: List[str] = ["white", "blue", "green", "purple", "black"]
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.models import Team, User


def _create_default_app_items(
    team: "Team", created_by: Optional["User"] = None, name: Optional[str] = "My App Dashboard"
) -> Dashboard:
    dashboard = Dashboard.objects.create(name=name, pinned=True, team=team, created_by=created_by)

    Insight.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Daily Active Users (DAUs)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        description="Shows the number of unique users that use your app everyday.",
    )

    Insight.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Cumulative DAUs",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            DATE_FROM: "-30d",
            DISPLAY: TRENDS_CUMULATIVE,
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        color=random.choice(DASHBOARD_COLORS),
        description="Shows the total cumulative number of unique users that have been using your app.",
    )

    Insight.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Repeat users over time",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            ENTITY_ID: "$pageview",
            ENTITY_TYPE: TREND_FILTER_TYPE_EVENTS,
            INTERVAL: "day",
            SHOWN_AS: TRENDS_STICKINESS,
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        color=random.choice(DASHBOARD_COLORS),
        description="Shows you how many users visited your app for a specific number of days "
        '(e.g. a user that visited your app twice in the time period will be shown under "2 days").',
    )

    Insight.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Sample - Purchase conversion funnel",
        filters={
            TREND_FILTER_TYPE_EVENTS: [
                {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS, "order": 0},
                {
                    "id": "$autocapture",
                    "name": "Clicked purchase button",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    PROPERTIES: [
                        {"key": "$event_type", "type": "event", "value": "click"},
                        {"key": "text", "type": "element", "value": "Purchase"},
                    ],
                    "order": 1,
                },
                {
                    "id": "$autocapture",
                    "name": "Submitted checkout form",
                    "type": TREND_FILTER_TYPE_EVENTS,
                    PROPERTIES: [
                        {"key": "$event_type", "type": "event", "value": "submit"},
                        {"key": "$pathname", "type": "event", "value": "/purchase"},
                    ],
                    "order": 2,
                },
                {"id": "Order Completed", "name": "Order Completed", "type": TREND_FILTER_TYPE_EVENTS, "order": 3},
            ],
            INSIGHT: "FUNNELS",
        },
        last_refresh=now(),
        is_sample=True,
        description="This is a sample of how a user funnel could look like. It represents the number of users that performed "
        "a specific action at each step.",
    )

    Insight.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Users by browser (last 2 weeks)",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            DATE_FROM: "-14d",
            INTERVAL: "day",
            BREAKDOWN_TYPE: "person",
            BREAKDOWN: "$browser",
            DISPLAY: TRENDS_PIE,
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        description="Shows a breakdown of browsers used to visit your app per unique users in the last 14 days.",
    )

    Insight.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Users by traffic source",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}],
            INTERVAL: "day",
            BREAKDOWN_TYPE: "event",
            BREAKDOWN: "$initial_referring_domain",
            INSIGHT: INSIGHT_TRENDS,
        },
        last_refresh=now(),
        description="Shows a breakdown of where unique users came from when visiting your app.",
    )

    return dashboard


def _create_open_startup(
    team: "Team", created_by: Optional["User"] = None, name: Optional[str] = "Open Startup"
) -> None:
    dashboard = Dashboard.objects.create(
        name=name,
        description='Instantly join the ranks of an open startup. Share your metrics, be publicly accountable. Click "send or share" at the top right to get a snippet you can embed in your website.',
        team=team,
        created_by=created_by,
    )
    items = [
        {
            "name": "Weekly pageviews",
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "actions": [],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "-90d",
                "properties": [],
                "filter_test_accounts": True,
            },
            "layouts": {
                "lg": {"h": 5, "w": 6, "x": 18, "y": 0},
                "sm": {"h": 5, "w": 4, "x": 4, "y": 0, "moved": False, "static": False},
                "xs": {"h": 5, "w": 6, "x": 0, "y": 15},
                "xxs": {"h": 5, "w": 2, "x": 0, "y": 15},
            },
            "color": "green",
            "description": "",
        },
        {
            "name": "Conversion funnel",
            "filters": {
                "events": [
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 1,
                        "custom_name": "Replace me!",
                    },
                ],
                "actions": [],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "exclusions": [],
                "properties": [],
                "funnel_to_step": 1,
                "funnel_viz_type": "steps",
                "funnel_from_step": 0,
                "filter_test_accounts": True,
            },
            "layouts": {
                "lg": {"h": 5, "w": 6, "x": 6, "y": 5},
                "sm": {"h": 8, "w": 4, "x": 8, "y": 5, "moved": False, "static": False},
                "xs": {"h": 5, "w": 6, "x": 0, "y": 25},
                "xxs": {"h": 5, "w": 2, "x": 0, "y": 25},
            },
            "description": "How many users go from visiting your home page to signing up. Replace the second pageview with the correct pageview or a sign up event.",
        },
        {
            "name": "Traffic source",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "name": "$pageview", "type": "events", "order": 0}],
                "actions": [],
                "display": "ActionsBarValue",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$initial_referring_domain",
                "date_from": "-90d",
                "new_entity": [],
                "properties": [],
                "breakdown_type": "person",
                "filter_test_accounts": True,
            },
            "layouts": {
                "lg": {"h": 5, "w": 6, "x": 0, "y": 5},
                "sm": {"h": 8, "w": 4, "x": 0, "y": 5, "moved": False, "static": False},
                "xs": {"h": 5, "w": 6, "x": 0, "y": 20},
                "xxs": {"h": 5, "w": 2, "x": 0, "y": 20},
            },
            "description": "Where your traffic is coming from",
        },
        {
            "name": "Weekly Active Users",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "name": "$pageview", "type": "events", "order": 0}],
                "actions": [],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "-90d",
                "new_entity": [],
                "properties": [],
                "filter_test_accounts": True,
            },
            "layouts": {
                "lg": {"h": 5, "w": 6, "x": 6, "y": 0},
                "sm": {"h": 5, "w": 4, "x": 0, "y": 0, "moved": False, "static": False},
                "xs": {"h": 5, "w": 6, "x": 0, "y": 5},
                "xxs": {"h": 5, "w": 2, "x": 0, "y": 5},
            },
            "color": "blue",
        },
        {
            "name": "GitHub stars",
            "filters": {
                "events": [{"id": "Github Star", "name": "Github Star", "type": "events", "order": 0}],
                "actions": [],
                "compare": False,
                "display": "ActionsLineGraphCumulative",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "all",
                "new_entity": [],
                "properties": [],
                "filter_test_accounts": False,
            },
            "layouts": {
                "lg": {"h": 5, "w": 6, "x": 0, "y": 0},
                "sm": {"h": 8, "w": 4, "x": 4, "y": 5, "moved": False, "static": False},
                "xs": {"h": 5, "w": 6, "x": 0, "y": 0},
                "xxs": {"h": 5, "w": 2, "x": 0, "y": 0},
            },
            "color": "black",
            "description": "Show the number of stars your project has. To use, enable the GitHub stars plugin.",
        },
        {
            "name": "Your key metric!",
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "actions": [],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "-90d",
                "properties": [],
                "filter_test_accounts": True,
            },
            "layouts": {
                "lg": {"h": 5, "w": 6, "x": 12, "y": 0},
                "sm": {"h": 5, "w": 4, "x": 8, "y": 0, "moved": False, "static": False},
                "xs": {"h": 5, "w": 6, "x": 0, "y": 10},
                "xxs": {"h": 5, "w": 2, "x": 0, "y": 10},
            },
            "color": "purple",
            "description": "User sign ups, bookings, checkouts. Change 'Pageview' to the event that's relevant to you.",
        },
    ]
    for item in items:
        Insight.objects.create(dashboard=dashboard, created_by=created_by, team=team, **item)
    return dashboard


DASHBOARD_TEMPLATES: Dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
    "OPEN_STARTUP": _create_open_startup,
}


def create_dashboard_from_template(
    template_key: str, team: "Team", created_by: Optional["User"] = None, name: Optional[str] = None
) -> Dashboard:

    if template_key not in DASHBOARD_TEMPLATES:
        raise AttributeError(f"Invalid template key `{template_key}` provided.")

    return DASHBOARD_TEMPLATES[template_key](team, created_by, name)
