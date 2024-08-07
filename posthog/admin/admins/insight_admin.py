from django.contrib import admin
from django.utils.html import format_html

from posthog.models import Insight


class InsightAdmin(admin.ModelAdmin):
    exclude = ("layouts",)

    list_display = (
        "id",
        "short_id",
        "effective_name",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "short_id", "effective_name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "short_id", "team__name", "team__organization__name")
    readonly_fields = ("deprecated_tags", "deprecated_tags_v2", "dive_dashboard")
    autocomplete_fields = ("team", "dashboard", "created_by", "last_modified_by")
    ordering = ("-created_at",)

    def effective_name(self, insight: Insight):
        return insight.name or format_html("<i>{}</>", insight.derived_name)

    def team_link(self, insight: Insight):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            insight.team.pk,
            insight.team.name,
        )

    def organization_link(self, insight: Insight):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            insight.team.organization.pk,
            insight.team.organization.name,
        )
