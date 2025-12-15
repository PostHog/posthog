from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import ColumnConfiguration


class ColumnConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "context_key",
        "team_link",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id", "context_key")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "context_key", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, config: ColumnConfiguration):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[config.team.pk]),
            config.team.name,
        )
