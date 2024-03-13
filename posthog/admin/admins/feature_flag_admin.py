from django.contrib import admin
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
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, flag: FeatureFlag):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            flag.team.pk,
            flag.team.name,
        )
