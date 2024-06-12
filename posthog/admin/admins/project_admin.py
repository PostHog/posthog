from django.contrib import admin
from django.utils.html import format_html

from posthog.admin.inlines.team_inline import TeamInline
from posthog.models import Project


class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_link",
        "organization_id",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("organization",)
    search_fields = (
        "id",
        "name",
        "organization__id",
        "organization__name",
    )
    readonly_fields = ["organization", "created_at"]
    inlines = [TeamInline]

    def organization_link(self, project: Project):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            project.organization.pk,
            project.organization.name,
        )
