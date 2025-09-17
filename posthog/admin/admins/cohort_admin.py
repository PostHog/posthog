from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import Cohort


class CohortAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, cohort: Cohort):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[cohort.team.pk]),
            cohort.team.name,
        )
