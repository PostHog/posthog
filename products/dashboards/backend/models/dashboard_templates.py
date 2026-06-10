from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q, UniqueConstraint

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

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True)
    template_name = models.CharField(max_length=400, null=True, blank=True)
    dashboard_description = models.CharField(max_length=400, null=True, blank=True)
    dashboard_filters = models.JSONField(null=True, blank=True)
    tiles = models.JSONField(blank=True, null=True)
    variables = models.JSONField(null=True, blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=255), blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(blank=True, null=True)
    image_url = models.CharField(max_length=8201, null=True, blank=True)
    scope = models.CharField(max_length=24, choices=Scope, null=True, blank=True)
    # URL length for browsers can be as much as 64Kb
    # see https://stackoverflow.com/questions/417142/what-is-the-maximum-length-of-a-url-in-different-browsers
    # but GitHub apparently is more likely 8kb https://stackoverflow.com/a/64565317
    github_url = models.CharField(max_length=8201, null=True, blank=True)
    # where this template is available, e.g. "general" and/or "onboarding"
    availability_contexts = ArrayField(models.CharField(max_length=255), blank=True, null=True)
    is_featured = models.BooleanField(
        default=False,
        help_text="Manually curated; used to highlight templates in the UI.",
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=[
                    "template_name",
                    "team",
                ],
                condition=Q(deleted__isnull=True) | Q(deleted=False),
                name="unique_template_name_per_team",
            ),
        ]
        db_table = "posthog_dashboardtemplate"

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
            dashboard_description=(
                "How people use your product and whether they come back: active users, retention, and "
                "conversion. Built automatically from your events. For traffic and acquisition detail, "
                "see Web analytics."
            ),
            dashboard_filters={},
            tiles=[
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": (
                        "# 👋 Start here\n\n"
                        "This is your starter dashboard: a quick read on how people use your product and "
                        "whether they come back. Edit any tile, or duplicate the dashboard to make it your own."
                    ),
                    "layouts": {
                        "sm": {"h": 2, "w": 12, "x": 0, "y": 0, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 0, "minH": 1, "minW": 1},
                    },
                },
                {
                    "name": "Active users (last 30 days)",
                    "type": "INSIGHT",
                    "color": "blue",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {
                                    "kind": "GroupNode",
                                    "operator": "OR",
                                    "nodes": [
                                        {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"},
                                        {"kind": "EventsNode", "event": "$screen", "name": "$screen"},
                                    ],
                                    "math": "dau",
                                    "name": "Pageview or screen",
                                }
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-30d", "explicitDate": False},
                            "properties": [],
                            "trendsFilter": {
                                "display": "BoldNumber",
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
                        "sm": {"h": 3, "w": 6, "x": 0, "y": 2, "minH": 3, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 3, "minH": 3, "minW": 1},
                    },
                    "description": "Unique people who used your app in the last 30 days. A quick pulse on your overall reach.",
                },
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": (
                        "## Looking for traffic numbers?\n\n"
                        "Pageviews, sessions, top pages, referrers, and where visitors come from all live in "
                        "Web analytics, updated automatically."
                    ),
                    "layouts": {
                        "sm": {"h": 3, "w": 6, "x": 6, "y": 2, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 6, "minH": 1, "minW": 1},
                    },
                },
                {
                    "name": "Daily active users (DAUs)",
                    "type": "INSIGHT",
                    "color": "blue",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {
                                    "kind": "GroupNode",
                                    "operator": "OR",
                                    "nodes": [
                                        {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"},
                                        {"kind": "EventsNode", "event": "$screen", "name": "$screen"},
                                    ],
                                    "math": "dau",
                                    "name": "Pageview or screen",
                                }
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
                        "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 9, "minH": 5, "minW": 1},
                    },
                    "description": "Unique people who use your app each day. Watch for steady growth or sudden drops.",
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
                                {
                                    "kind": "GroupNode",
                                    "operator": "OR",
                                    "nodes": [
                                        {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"},
                                        {"kind": "EventsNode", "event": "$screen", "name": "$screen"},
                                    ],
                                    "math": "dau",
                                    "name": "Pageview or screen",
                                }
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
                        "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 14, "minH": 5, "minW": 1},
                    },
                    "description": "Unique people who use your app each week. Smooths out daily noise to show the underlying trend.",
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
                        "sm": {"h": 5, "w": 12, "x": 0, "y": 10, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 19, "minH": 5, "minW": 1},
                    },
                    "description": "How many people come back week after week after their first visit. The clearest signal of whether your product is sticky.",
                },
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": (
                        "## Turning visits into actions\n\n"
                        "A funnel from page view to click. Swap in your own events (signup, purchase, upgrade) "
                        "to measure real conversion."
                    ),
                    "layouts": {
                        "sm": {"h": 2, "w": 12, "x": 0, "y": 15, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 24, "minH": 1, "minW": 1},
                    },
                },
                {
                    "name": "Visit to interaction funnel",
                    "type": "INSIGHT",
                    "color": "black",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "FunnelsQuery",
                            "series": [
                                {
                                    "kind": "EventsNode",
                                    "name": "$pageview",
                                    "event": "$pageview",
                                    "custom_name": "Viewed a page",
                                },
                                {
                                    "kind": "EventsNode",
                                    "name": "$autocapture",
                                    "event": "$autocapture",
                                    "custom_name": "Clicked something",
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
                            "breakdownFilter": {"breakdown_type": "event"},
                            "filterTestAccounts": False,
                        },
                    },
                    "layouts": {
                        "sm": {"h": 5, "w": 12, "x": 0, "y": 17, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 27, "minH": 5, "minW": 1},
                    },
                    "description": "Of people who land on a page, how many go on to interact. Replace these steps with your own events to track real conversions.",
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
