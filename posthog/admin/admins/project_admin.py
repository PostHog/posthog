from django.contrib import admin
from django.urls import reverse
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
    autocomplete_fields = ["organization"]
    readonly_fields = ["created_at"]
    inlines = [TeamInline]

    def organization_link(self, project: Project):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[project.organization.pk]),
            project.organization.name,
        )
