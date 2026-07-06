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
        ORGANIZATION = "organization", "Organization"
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
        The authoritative hardcoded "Product analytics" template the rest of the codebase relies on
        (the DEFAULT_APP seed, the DB-absent fallback in create_dashboard_from_template, and the global
        template seed used in tests). It is intentionally the legacy shape; new projects get the
        refreshed layout via default_signup_template().

        This OG template is not stored in https://github.com/PostHog/templates-repository
        The system assumes this template is always present and doesn't wait to import it from the template repository
        """
        return DashboardTemplate.legacy_signup_template()

    @staticmethod
    def default_signup_template() -> "DashboardTemplate":
        """
        Refreshed signup dashboard given to every new non-demo project's primary dashboard.
        This OG template is not stored in https://github.com/PostHog/templates-repository
        The system assumes this template is always present and doesn't wait to import it from the template repository
        """
        return DashboardTemplate(
            template_name="Product analytics",
            dashboard_description=(
                "How people use your app at a glance: traffic, retention, where visitors come from, and "
                "whether they take action. Built from automatically captured events, so it works on day one. "
                "Swap in your own events to make it yours."
            ),
            dashboard_filters={},
            tiles=[
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": (
                        "# 👋 Start here\n\n"
                        "Everything below is captured automatically (pageviews, clicks, sessions, and location), "
                        "so this dashboard fills in from day one with no extra setup. The headline numbers will "
                        "feel familiar; the retention and funnel tiles are where you point PostHog at your own "
                        "events. Edit any tile, or duplicate the dashboard to make it your own."
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
                        "sm": {"h": 3, "w": 4, "x": 0, "y": 2, "minH": 3, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 3, "minH": 3, "minW": 1},
                    },
                    "description": "Unique people who used your app in the last 30 days. A quick pulse on your overall reach.",
                },
                {
                    "name": "Sessions (last 7 days)",
                    "type": "INSIGHT",
                    "color": "blue",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {
                                    "kind": "EventsNode",
                                    "math": "unique_session",
                                    "name": "$pageview",
                                    "event": "$pageview",
                                }
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-7d", "explicitDate": False},
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
                        "sm": {"h": 3, "w": 4, "x": 4, "y": 2, "minH": 3, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 6, "minH": 3, "minW": 1},
                    },
                    "description": "Distinct visits in the last 7 days. A session groups everything one person does in a single sitting.",
                },
                {
                    "name": "Pageviews (last 7 days)",
                    "type": "INSIGHT",
                    "color": "blue",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {"kind": "EventsNode", "math": "total", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-7d", "explicitDate": False},
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
                        "sm": {"h": 3, "w": 4, "x": 8, "y": 2, "minH": 3, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 9, "minH": 3, "minW": 1},
                    },
                    "description": "Total pages viewed in the last 7 days, repeat views included. The classic traffic-volume number.",
                },
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": (
                        "## Are people coming back?\n\n"
                        "Active users show your trend; retention shows how many return after their first visit. "
                        "The clearest sign your product is sticky."
                    ),
                    "layouts": {
                        "sm": {"h": 2, "w": 12, "x": 0, "y": 5, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 12, "minH": 1, "minW": 1},
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
                        "sm": {"h": 5, "w": 6, "x": 0, "y": 7, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 1},
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
                        "sm": {"h": 5, "w": 6, "x": 6, "y": 7, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 1},
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
                        "sm": {"h": 5, "w": 12, "x": 0, "y": 12, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 1},
                    },
                    "description": "How many people come back week after week after their first visit. The clearest signal of whether your product is sticky.",
                },
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": ("## Where your visitors come from\n\nThe sites and channels sending people to your app."),
                    "layouts": {
                        "sm": {"h": 2, "w": 12, "x": 0, "y": 17, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 30, "minH": 1, "minW": 1},
                    },
                },
                {
                    "name": "Top referrers",
                    "type": "INSIGHT",
                    "color": "purple",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {
                            "kind": "TrendsQuery",
                            "series": [
                                {"kind": "EventsNode", "math": "dau", "name": "$pageview", "event": "$pageview"}
                            ],
                            "interval": "day",
                            "dateRange": {"date_from": "-7d", "explicitDate": False},
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
                        "sm": {"h": 5, "w": 12, "x": 0, "y": 19, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 33, "minH": 5, "minW": 1},
                    },
                    "description": "Which sites send you the most visitors, like search, social, and direct. Your acquisition channels at a glance.",
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
                        "sm": {"h": 2, "w": 12, "x": 0, "y": 24, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 38, "minH": 1, "minW": 1},
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
                        "sm": {"h": 5, "w": 12, "x": 0, "y": 26, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 41, "minH": 5, "minW": 1},
                    },
                    "description": "Of people who land on a page, how many go on to interact. Replace these steps with your own events to track real conversions.",
                },
                {
                    "type": "TEXT",
                    "color": None,
                    "transparent_background": True,
                    "body": (
                        "## What to do next\n\n"
                        "You've got the numbers. Watch how people actually behave, explore raw events, or dig "
                        "into traffic and acquisition."
                    ),
                    "layouts": {
                        "sm": {"h": 2, "w": 12, "x": 0, "y": 31, "minH": 1, "minW": 3},
                        "xs": {"h": 3, "w": 1, "x": 0, "y": 46, "minH": 1, "minW": 1},
                    },
                },
                {
                    "type": "BUTTON",
                    "color": None,
                    "transparent_background": True,
                    "url": "/replay/home",
                    "text": "Watch session replays",
                    "placement": "left",
                    "style": "primary",
                    "layouts": {
                        "sm": {"h": 1, "w": 4, "x": 0, "y": 33, "minH": 1, "minW": 2},
                        "xs": {"h": 1, "w": 1, "x": 0, "y": 49, "minH": 1, "minW": 1},
                    },
                },
                {
                    "type": "BUTTON",
                    "color": None,
                    "transparent_background": True,
                    "url": "/web",
                    "text": "Open web analytics",
                    "placement": "left",
                    "style": "secondary",
                    "layouts": {
                        "sm": {"h": 1, "w": 4, "x": 4, "y": 33, "minH": 1, "minW": 2},
                        "xs": {"h": 1, "w": 1, "x": 0, "y": 50, "minH": 1, "minW": 1},
                    },
                },
                {
                    "type": "BUTTON",
                    "color": None,
                    "transparent_background": True,
                    "url": "/activity/explore",
                    "text": "Browse activity",
                    "placement": "left",
                    "style": "secondary",
                    "layouts": {
                        "sm": {"h": 1, "w": 4, "x": 8, "y": 33, "minH": 1, "minW": 2},
                        "xs": {"h": 1, "w": 1, "x": 0, "y": 51, "minH": 1, "minW": 1},
                    },
                },
            ],
            tags=[],
        )

    @staticmethod
    def legacy_signup_template() -> "DashboardTemplate":
        """
        The legacy "Product analytics" dashboard, still used by the DEFAULT_APP template seed.
        This OG template is not stored in https://github.com/PostHog/templates-repository
        The system assumes this template is always present and doesn't wait to import it from the template repository
        """
        return DashboardTemplate(
            template_name="Product analytics",
            dashboard_description=(
                "A starter view of how people use your app: how many visit, whether they come back, "
                "where traffic comes from, and how they move through your pages."
            ),
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
                        "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
                    },
                    "description": "Shows the number of unique users that view a page or screen in your app every day.",
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
                        "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
                    },
                    "description": "Shows the number of unique users that view a page or screen in your app every week.",
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
                    "description": "Weekly retention of your users based on pageviews.",
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
                    "description": "How many of your users are new, returning, resurrecting, or dormant each week based on pageviews.",
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
                    "description": "Shows the most common referring domains for your users over the past 14 days. Pageviews only.",
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
                    "description": "This example funnel shows how many of your users have completed 3 page views, broken down by browser. Pageviews only.",
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
