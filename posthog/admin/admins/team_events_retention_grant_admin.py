from django.contrib import admin
from django.http import HttpRequest

from posthog.models.team import TeamEventsRetentionGrant


@admin.register(TeamEventsRetentionGrant)
class TeamEventsRetentionGrantAdmin(admin.ModelAdmin):
    list_display = ("team", "retention_months", "updated_at")
    list_select_related = ("team",)
    search_fields = ("team__id", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    readonly_fields = ("created_at", "updated_at")
    fields = ("team", "retention_months", "note", "created_at", "updated_at")

    def get_readonly_fields(self, request: HttpRequest, obj: TeamEventsRetentionGrant | None = None) -> tuple[str, ...]:
        # The team is the primary key, so changing it would save a second grant and leave the first in place.
        if obj is None:
            return self.readonly_fields
        return (*self.readonly_fields, "team")
