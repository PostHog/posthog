from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from posthog.models import Dashboard, DashboardItem

DEFAULT_DASHBOARD_APP = "DEFAULT_APP"
DEFAULT_DASHBOARD_WEB = "DEFAULT_WEB"


def create_default_app_dashboard_items(dashboard: Dashboard):
    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Views this week",
        type=TRENDS_LINEAR,
        filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}]},
        last_refresh=now(),
    )

    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Most popular phones this week",
        type="ActionsTable",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}],
            "display": "ActionsTable",
            "breakdown": "$browser",
        },
        last_refresh=now(),
    )

    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Daily Active Users",
        type=TRENDS_LINEAR,
        filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}]},
        last_refresh=now(),
    )
    return dashboard


def create_default_web_dashboard_items(dashboard: Dashboard):
    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Pageviews this week",
        type=TRENDS_LINEAR,
        filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}]},
        last_refresh=now(),
    )
    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Most popular browsers this week",
        type="ActionsTable",
        filters={
            TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}],
            "display": "ActionsTable",
            "breakdown": "$browser",
        },
        last_refresh=now(),
    )
    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Daily Active Users",
        type=TRENDS_LINEAR,
        filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}]},
        last_refresh=now(),
    )
    return dashboard
