from typing import Dict

from django.contrib.postgres.fields import ArrayField
from django.db.models import UniqueConstraint

from posthog import models
from posthog.models.utils import UUIDModel


class DashboardTemplate(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    template_name: models.CharField = models.CharField(max_length=400, null=True)
    dashboard_description: models.CharField = models.CharField(max_length=400, null=True)
    dashboard_filters: models.JSONField = models.JSONField(null=True)
    tiles: models.JSONField = models.JSONField(default=list)
    tags: ArrayField = ArrayField(models.CharField(max_length=255), default=list)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=[
                    "template_name",
                    "team",
                ],
                name="unique_template_name_per_team",
            ),
        ]

    @staticmethod
    def original_template() -> Dict:
        return {
            "template_name": "Product analytics",
            "source_dashboard": None,
            "dashboard_description": "",
            "dashboard_filters": {},
            "tiles": [
                {
                    "name": "Daily active users (DAUs)",
                    "type": "INSIGHT",
                    "color": "blue",
                    "filters": {
                        "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                        "display": "BoldNumber",
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
                        "events": [
                            {
                                "id": "$pageview",
                                "math": "weekly_active",
                                "type": "events",
                            }
                        ],
                        "insight": "TRENDS",
                        "interval": "week",
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
                            {
                                "id": "$pageview",
                                "type": "events",
                                "order": 0,
                                "custom_name": "First page view",
                            },
                            {
                                "id": "$pageview",
                                "type": "events",
                                "order": 1,
                                "custom_name": "Second page view",
                            },
                            {
                                "id": "$pageview",
                                "type": "events",
                                "order": 2,
                                "custom_name": "Third page view",
                            },
                        ],
                        "layout": "horizontal",
                        "display": "FunnelViz",
                        "insight": "FUNNELS",
                        "interval": "day",
                        "breakdowns": [{"type": "event", "property": "$browser"}],
                        "exclusions": [],
                        "breakdown_type": "event",
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
            "scope": "global",
        }
