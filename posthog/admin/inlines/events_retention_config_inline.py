from django.contrib import admin

from posthog.models.events_retention_config import OrganizationEventsRetentionConfig, TeamEventsRetentionConfig


class OrganizationEventsRetentionConfigInline(admin.StackedInline):
    model = OrganizationEventsRetentionConfig
    verbose_name = "Events retention"
    verbose_name_plural = "Events retention"
    extra = 1
    max_num = 1
    classes = ("collapse",)
    fields = ["default_events_retention_months", "min_events_retention_months", "max_events_retention_months"]


class TeamEventsRetentionConfigInline(admin.StackedInline):
    model = TeamEventsRetentionConfig
    verbose_name = "Events retention"
    verbose_name_plural = "Events retention"
    extra = 1
    max_num = 1
    classes = ("collapse",)
    fields = ["events_retention_months"]
