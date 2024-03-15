from django.contrib import admin
from django.utils.html import format_html

from posthog.models import Experiment


class ExperimentAdmin(admin.ModelAdmin):
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

    def team_link(self, experiment: Experiment):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            experiment.team.pk,
            experiment.team.name,
        )
