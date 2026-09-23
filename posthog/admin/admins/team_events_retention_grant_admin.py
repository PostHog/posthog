from django.contrib import admin

from posthog.models.team import TeamEventsRetentionGrant


@admin.register(TeamEventsRetentionGrant)
class TeamEventsRetentionGrantAdmin(admin.ModelAdmin):
    list_display = ("team", "retention_months", "updated_at")
    list_select_related = ("team",)
    search_fields = ("team__id", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    readonly_fields = ("created_at", "updated_at")
    fields = ("team", "retention_months", "note", "created_at", "updated_at")
