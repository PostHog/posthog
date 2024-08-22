from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import UniqueConstraint

from posthog.models.utils import UUIDModel


class DashboardTemplateManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)


class DashboardTemplate(UUIDModel):
    objects = DashboardTemplateManager()
    objects_including_soft_deleted = models.Manager()

    class Scope(models.TextChoices):
        """Visibility of the dashboard template"""

        ONLY_TEAM = "team", "Only team"
        GLOBAL = "global", "Global"
        FEATURE_FLAG = "feature_flag", "Feature Flag"

    team = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    template_name = models.CharField(max_length=400, null=True, blank=True)
    dashboard_description = models.CharField(max_length=400, null=True, blank=True)
    dashboard_filters = models.JSONField(null=True, blank=True)
    tiles = models.JSONField(blank=True, null=True)
    variables = models.JSONField(null=True, blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=255), blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(blank=True, null=True)
    image_url = models.CharField(max_length=8201, null=True, blank=True)
    scope = models.CharField(max_length=24, choices=Scope.choices, null=True, blank=True)
    # URL length for browsers can be as much as 64Kb
    # see https://stackoverflow.com/questions/417142/what-is-the-maximum-length-of-a-url-in-different-browsers
    # but GitHub apparently is more likely 8kb https://stackoverflow.com/a/64565317
    github_url = models.CharField(max_length=8201, null=True)

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
    def original_template() -> "DashboardTemplate":
        """
        This OG template is not stored in https://github.com/PostHog/templates-repository
        The system assumes this template is always present and doesn't wait to import it from the template repository
        """
        return DashboardTemplate(
            template_name="Product analytics",
            dashboard_description="",
            dashboard_filters={},
            tiles=[
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
                        "events": [
                            {
                                "id": "$pageview",
                                "math": "dau",
                                "type": "events",
                            }
                        ],
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
            tags=[],
        )

    @staticmethod
    def feature_flag_template(feature_flag_key: str) -> "DashboardTemplate":
        return DashboardTemplate(
            template_name=feature_flag_key + "Usage Information",
            dashboard_description="",
            dashboard_filters={},
            tiles=[
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
                        "events": [
                            {
                                "id": "$pageview",
                                "math": "dau",
                                "type": "events",
                            }
                        ],
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
            ],
        )
