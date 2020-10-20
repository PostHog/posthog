from typing import Callable, Dict

from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from posthog.models import Dashboard, DashboardItem


def _create_default_app_items(dashboard: Dashboard) -> None:

    DashboardItem.objects.create(
        team=dashboard.team,
        dashboard=dashboard,
        name="Daily Active Users (DAUs)",
        type=TRENDS_LINEAR,
        filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}]},
        last_refresh=now(),
    )


DASHBOARD_TEMPLATES: Dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
}


def create_dashboard_from_template(template_key: str, dashboard: Dashboard) -> None:

    if template_key not in DASHBOARD_TEMPLATES:
        raise AttributeError(f"Invalid template key `{template_key}` provided.")

    DASHBOARD_TEMPLATES[template_key](dashboard)
