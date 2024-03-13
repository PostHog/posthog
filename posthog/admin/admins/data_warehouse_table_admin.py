from django.contrib import admin
from django.utils.html import format_html

from posthog.models import Dashboard


class DataWarehouseTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "format",
        "url_pattern",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            dashboard.team.pk,
            dashboard.team.name,
        )

    def organization_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            dashboard.team.organization.pk,
            dashboard.team.organization.name,
        )
