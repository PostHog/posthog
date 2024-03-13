from django.contrib import admin
from django.utils.html import format_html

from posthog.models import Dashboard, DashboardTile


class DashboardTileInline(admin.TabularInline):
    extra = 0
    model = DashboardTile
    autocomplete_fields = ("insight", "text")
    readonly_fields = ("filters_hash",)


class DashboardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    readonly_fields = (
        "last_accessed_at",
        "deprecated_tags",
        "deprecated_tags_v2",
        "share_token",
    )
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at", "creation_mode")
    inlines = (DashboardTileInline,)

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
