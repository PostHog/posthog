from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import FeatureFlag


class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "key")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "key", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by", "last_modified_by")
    readonly_fields = ("usage_dashboard",)
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, flag: FeatureFlag):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[flag.team.pk]),
            flag.team.name,
        )
