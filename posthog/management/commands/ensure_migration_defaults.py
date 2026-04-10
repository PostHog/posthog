from __future__ import annotations

import importlib
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand

from posthog.demo.dashboard_template_seeds import seed_dev_dashboard_templates
from posthog.models.data_color_theme import DataColorTheme

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

# 0537 still references posthog.DataColorTheme which hasn't moved
_migration_0537 = importlib.import_module("posthog.migrations.0537_data_color_themes")
add_default_themes = _migration_0537.add_default_themes

# Template data originally from migrations 0310 and 0328.
# Cannot call those migration functions directly because they use
# apps.get_model("posthog", "DashboardTemplate") which no longer
# resolves after the model moved to the dashboards product app.
_PRODUCT_ANALYTICS_TEMPLATE: dict[str, Any] = {
    "template_name": "Product analytics",
    "dashboard_description": (
        "High-level overview of your product including daily active users, "
        "weekly active users, retention, and growth accounting."
    ),
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Daily active users (DAUs)",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your app every day.",
        },
        {
            "name": "Weekly active users (WAUs)",
            "type": "INSIGHT",
            "color": "green",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "-90d",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your app every week.",
        },
        {
            "name": "Retention",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "period": "Week",
                "insight": "RETENTION",
                "target_entity": {"id": "$pageview", "type": "events"},
                "retention_type": "retention_first_time",
                "returning_entity": {"id": "$pageview", "type": "events"},
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3},
            },
            "description": "Weekly retention of your users.",
        },
        {
            "name": "Growth accounting",
            "type": "INSIGHT",
            "color": "purple",
            "filters": {
                "events": [{"id": "$pageview", "type": "events"}],
                "insight": "LIFECYCLE",
                "interval": "week",
                "shown_as": "Lifecycle",
                "date_from": "-30d",
                "entity_type": "events",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3},
            },
            "description": "How many of your users are new, returning, resurrecting, or dormant each week.",
        },
        {
            "name": "Referring domain (last 14 days)",
            "type": "INSIGHT",
            "color": "black",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                "display": "ActionsBarValue",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$referring_domain",
                "date_from": "-14d",
                "breakdown_type": "event",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 10, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 3},
            },
            "description": "Shows the most common referring domains for your users over the past 14 days.",
        },
        {
            "name": "Pageview funnel, by browser",
            "type": "INSIGHT",
            "color": "green",
            "filters": {
                "events": [
                    {"id": "$pageview", "type": "events", "order": 0, "custom_name": "First page view"},
                    {"id": "$pageview", "type": "events", "order": 1, "custom_name": "Second page view"},
                    {"id": "$pageview", "type": "events", "order": 2, "custom_name": "Third page view"},
                ],
                "layout": "horizontal",
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "exclusions": [],
                "breakdown_type": "event",
                "breakdown": "$browser",
                "funnel_viz_type": "steps",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3},
            },
            "description": "This example funnel shows how many of your users have completed 3 page views, broken down by browser.",
        },
    ],
    "tags": [],
}

_FEATURE_FLAG_TEMPLATE: dict[str, Any] = {
    "template_name": "Flagged Feature Usage",
    "dashboard_description": (
        "Overview of engagement with the flagged feature including daily active users and weekly active users."
    ),
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Daily active users (DAUs)",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "events": ["{ENGAGEMENT}"],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your feature every day.",
        },
        {
            "name": "Weekly active users (WAUs)",
            "type": "INSIGHT",
            "color": "green",
            "filters": {
                "events": ["{ENGAGEMENT}"],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "-90d",
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your feature every week.",
        },
    ],
    "tags": [],
    "variables": [
        {
            "id": "ENGAGEMENT",
            "name": "Engagement",
            "type": "event",
            "default": {"name": "$pageview", "id": "$pageview"},
            "required": True,
            "description": "The event you use to define a user using the new feature",
        }
    ],
    "scope": "feature_flag",
}


class Command(BaseCommand):
    help = "Ensure default data from migrations exists for schema-only restores."

    def handle(self, *args: Any, **options: Any) -> None:
        created_items: list[str] = []

        if not DataColorTheme.objects.filter(team__isnull=True, name="Default Theme").exists():
            add_default_themes(apps, None)
            created_items.append("Data color theme: Default Theme")

        for template_data in (_PRODUCT_ANALYTICS_TEMPLATE, _FEATURE_FLAG_TEMPLATE):
            name = template_data["template_name"]
            if not DashboardTemplate.objects.filter(template_name=name, team__isnull=True).exists():
                DashboardTemplate.objects.create(**template_data)
                created_items.append(f"Dashboard template: {name}")

        for name in seed_dev_dashboard_templates():
            created_items.append(f"Dashboard template: {name}")

        if created_items:
            self.stdout.write("Created defaults:\n- " + "\n- ".join(created_items))
        else:
            self.stdout.write("Default migration data already present.")
