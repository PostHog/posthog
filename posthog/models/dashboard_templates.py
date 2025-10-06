from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import UniqueConstraint

from posthog.models.utils import RootTeamManager, RootTeamMixin, UUIDTModel


class DashboardTemplateManager(RootTeamManager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)


class DashboardTemplate(UUIDTModel, RootTeamMixin):
    objects = DashboardTemplateManager()  # type: ignore
    objects_including_soft_deleted = RootTeamManager()

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
    github_url = models.CharField(max_length=8201, null=True, blank=True)
    # where this template is available, e.g. "general" and/or "onboarding"
    availability_contexts = ArrayField(models.CharField(max_length=255), blank=True, null=True)

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

    def __str__(self):
        return self.template_name

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
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {"kind": "EventsNode", "math": "dau", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-30d", "explicitDate": False},
                            "properties": [],
                            "trendsFilter": {
                                "display": "ActionsLineGraph",
                                "showLegend": False,
                                "yAxisScaleType": "linear",
                                "showValuesOnSeries": False,
                                "smoothingIntervals": 1,
                                "showPercentStackView": False,
                                "aggregationAxisFormat": "numeric",
                                "showAlertThresholdLines": False,
                            },
                            "breakdownFilter": {"breakdown_type": "event"},
                            "filterTestAccounts": False,
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
                            "series": [
                                {"kind": "EventsNode", "math": "dau", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "week",
                            "dateRange": {"date_from": "-90d", "explicitDate": False},
                            "properties": [],
                            "trendsFilter": {
                                "display": "ActionsLineGraph",
                                "showLegend": False,
                                "yAxisScaleType": "linear",
                                "showValuesOnSeries": False,
                                "smoothingIntervals": 1,
                                "showPercentStackView": False,
                                "aggregationAxisFormat": "numeric",
                                "showAlertThresholdLines": False,
                            },
                            "breakdownFilter": {"breakdown_type": "event"},
                            "filterTestAccounts": False,
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
                            "dateRange": {"date_from": "-7d", "explicitDate": False},
                            "properties": [],
                            "retentionFilter": {
                                "period": "Week",
                                "targetEntity": {"id": "$pageview", "type": "events"},
                                "retentionType": "retention_first_time",
                                "totalIntervals": 11,
                                "returningEntity": {"id": "$pageview", "type": "events"},
                            },
                            "filterTestAccounts": False,
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
                            "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview"}],
                            "interval": "week",
                            "dateRange": {"date_from": "-30d", "explicitDate": False},
                            "properties": [],
                            "lifecycleFilter": {"showLegend": False},
                            "filterTestAccounts": False,
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
                            "series": [
                                {"kind": "EventsNode", "math": "dau", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-14d", "explicitDate": False},
                            "properties": [],
                            "trendsFilter": {
                                "display": "ActionsBarValue",
                                "showLegend": False,
                                "yAxisScaleType": "linear",
                                "showValuesOnSeries": False,
                                "smoothingIntervals": 1,
                                "showPercentStackView": False,
                                "aggregationAxisFormat": "numeric",
                                "showAlertThresholdLines": False,
                            },
                            "breakdownFilter": {"breakdown": "$referring_domain", "breakdown_type": "event"},
                            "filterTestAccounts": False,
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
                                    "name": "$pageview",
                                    "event": "$pageview",
                                    "custom_name": "First page view",
                                },
                                {
                                    "kind": "EventsNode",
                                    "name": "$pageview",
                                    "event": "$pageview",
                                    "custom_name": "Second page view",
                                },
                                {
                                    "kind": "EventsNode",
                                    "name": "$pageview",
                                    "event": "$pageview",
                                    "custom_name": "Third page view",
                                },
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-7d", "explicitDate": False},
                            "properties": [],
                            "funnelsFilter": {
                                "layout": "horizontal",
                                "exclusions": [],
                                "funnelVizType": "steps",
                                "funnelOrderType": "ordered",
                                "funnelStepReference": "total",
                                "funnelWindowInterval": 14,
                                "breakdownAttributionType": "first_touch",
                                "funnelWindowIntervalUnit": "day",
                            },
                            "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"},
                            "filterTestAccounts": False,
                        },
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
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {"kind": "EventsNode", "math": "dau", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-30d", "explicitDate": False},
                            "properties": [],
                            "trendsFilter": {
                                "display": "ActionsLineGraph",
                                "showLegend": False,
                                "yAxisScaleType": "linear",
                                "showValuesOnSeries": False,
                                "smoothingIntervals": 1,
                                "showPercentStackView": False,
                                "aggregationAxisFormat": "numeric",
                                "showAlertThresholdLines": False,
                            },
                            "breakdownFilter": {"breakdown_type": "event"},
                            "filterTestAccounts": False,
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
                            "series": [
                                {"kind": "EventsNode", "math": "dau", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "week",
                            "dateRange": {"date_from": "-90d", "explicitDate": False},
                            "properties": [],
                            "trendsFilter": {
                                "display": "ActionsLineGraph",
                                "showLegend": False,
                                "yAxisScaleType": "linear",
                                "showValuesOnSeries": False,
                                "smoothingIntervals": 1,
                                "showPercentStackView": False,
                                "aggregationAxisFormat": "numeric",
                                "showAlertThresholdLines": False,
                            },
                            "breakdownFilter": {"breakdown_type": "event"},
                            "filterTestAccounts": False,
                        },
                    },
                    "layouts": {
                        "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
                    },
                    "description": "Shows the number of unique users that use your app every week.",
                },
            ],
        )
