from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models.dashboard_templates import DashboardTemplate


class DashboardTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "template_name",
        "deleted",
        "created_at",
        "created_by",
        "scope",
        "team_link",
    )
    list_display_links = ("template_name",)
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "template_name", "team__name", "team__organization__name")
    readonly_fields = ("team",)
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, template: DashboardTemplate):
        if template.team is None:
            return None
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[template.team.pk]),
            template.team.name,
        )
