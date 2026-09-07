from __future__ import annotations

import importlib
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand

from posthog.models.data_color_theme import DataColorTheme

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.demo.backend.facade.api import seed_dev_dashboard_templates

# 0537 still references posthog.DataColorTheme which hasn't moved
_migration_0537 = importlib.import_module("posthog.migrations.0537_data_color_themes")
add_default_themes = _migration_0537.add_default_themes

# Template data originally from migrations 0310 and 0328.
# Cannot call those migration functions directly because they use
# apps.get_model("posthog", "DashboardTemplate") which no longer
# resolves after the model moved to the dashboards product app.
# Tiles carry `query`, unlike the legacy `filters` those migrations wrote:
# `create_from_template` builds each insight from `query` alone, so a
# filters-shaped tile yields an insight with no definition at all.
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau"}],
                    "dateRange": {"date_from": "-30d"},
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau"}],
                    "dateRange": {"date_from": "-90d"},
                    "interval": "week",
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "RetentionQuery",
                    "dateRange": {},
                    "retentionFilter": {
                        "period": "Week",
                        "retentionType": "retention_first_time",
                        "targetEntity": {"id": "$pageview", "type": "events"},
                        "returningEntity": {"id": "$pageview", "type": "events"},
                        "meanRetentionCalculation": "simple",
                    },
                },
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "LifecycleQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}],
                    "dateRange": {"date_from": "-30d"},
                    "interval": "week",
                    "lifecycleFilter": {},
                },
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau"}],
                    "dateRange": {"date_from": "-14d"},
                    "breakdownFilter": {"breakdown": "$referring_domain"},
                    "trendsFilter": {"display": "ActionsBarValue"},
                    "compareFilter": {},
                },
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "custom_name": "First page view",
                        },
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "custom_name": "Second page view",
                        },
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "custom_name": "Third page view",
                        },
                    ],
                    "dateRange": {},
                    "interval": "day",
                    "breakdownFilter": {"breakdown": "$browser"},
                    "funnelsFilter": {"layout": "horizontal"},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3},
            },
            "description": "This example funnel shows how many of your users have completed 3 page views, broken down by browser.",
        },
    ],
    "tags": [],
    "scope": "global",
}

_FEATURE_FLAG_TEMPLATE: dict[str, Any] = {
    "template_name": "Flagged Feature Usage",
    "dashboard_description": (
        "Overview of engagement with the flagged feature including daily active users and weekly active users."
    ),
    "dashboard_filters": {},
    # `{ENGAGEMENT}` stands in for a series entry. The browser resolves it against
    # the variable below before the tiles reach the API, so no placeholder is stored.
    "tiles": [
        {
            "name": "Daily active users (DAUs)",
            "type": "INSIGHT",
            "color": "blue",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": ["{ENGAGEMENT}"],
                    "dateRange": {"date_from": "-30d"},
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
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
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": ["{ENGAGEMENT}"],
                    "dateRange": {"date_from": "-90d"},
                    "interval": "week",
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
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
