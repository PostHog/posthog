from django.contrib import admin

from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig


class TeamMarketingAnalyticsConfigInline(admin.StackedInline):
    model = TeamMarketingAnalyticsConfig
    extra = 0
    max_num = 1
    classes = ("collapse",)

    fieldsets = [
        (
            "Marketing Analytics Configuration",
            {
                "fields": ["_sources_map", "_conversion_goals"],
                "description": "Configure external data sources and conversion tracking for marketing analytics.",
            },
        ),
    ]

    def has_delete_permission(self, request, obj=None):
        return False  # Don't allow deletion of the config
